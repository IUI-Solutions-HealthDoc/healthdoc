#!/usr/bin/env python3
"""Repoint files on patient merge. Run from the repo root. Idempotent.

WHY
---
#365 fails test_repointing_covers_every_patient_fk:

    ['files'] have a foreign key to patients.id but are not in REPOINTED_ON_MERGE

Not a defect in #365. 0019 gave files a patient_id FK and nobody wired it into
approve_merge; the table only becomes visible to the guard when the files
router is registered, which is what this PR does. Third time the same guard
has caught a pre-existing gap this week — orders/prescriptions, then
fhir_bundle_transactions, now files.

REPOINT RATHER THAN EXEMPT
--------------------------
patient_merge_log is exempt because rewriting it would erase the evidence of
which patient merged into which. files is not evidence of the merge — it is
the patient's documents: photos, ID proofs, scanned consent, lab report PDFs.
After a merge the patient is the target, and files left on the dead source id
mean the surviving record's document list silently omits everything from
before the merge. That is the same failure _repoint_visits exists to prevent.

RAW SQL, NOT THE ORM MODEL
--------------------------
Importing FileRecord into patients/service.py would register it on
Base.metadata as a side effect of the import, changing which tables the guard
sees on branches that don't wire the files router. A plain UPDATE avoids that
— the table exists from 0019 either way.
"""
import pathlib
import sys

SVC = pathlib.Path("backend/app/patients/service.py")
if not SVC.exists():
    sys.exit("run me from the repo root")

text = SVC.read_text()
before = text

if '"files"' in text and "_repoint_files" in text:
    print("~ already applied")
    sys.exit(0)

# ------------------------------------------------------------------ the set
import re
m = re.search(r"REPOINTED_ON_MERGE: frozenset\[str\] = frozenset\(\s*\{([^}]*)\}\s*\)", text, re.S)
if not m:
    sys.exit("! REPOINTED_ON_MERGE not found in the expected shape")
if '"files"' in m.group(1):
    print("~ files already in REPOINTED_ON_MERGE")
else:
    members = m.group(1).strip().rstrip(",")
    text = text.replace(m.group(0),
                        "REPOINTED_ON_MERGE: frozenset[str] = frozenset(\n"
                        f"    {{{members}, \"files\"}}\n"
                        ")", 1)
    print("+ added files to REPOINTED_ON_MERGE")

# --------------------------------------------------------------- the helper
HELPER = '''async def _repoint_files(db: AsyncSession, *, source: Patient, target: Patient) -> None:
    """Moves source's files rows onto target.

    0019 created files with a patient_id FK and no repointing logic; the guard
    test only sees the table once the files router is registered, which #365
    does. Repointed rather than exempted: unlike patient_merge_log, which is
    the evidence of the merge and must never be rewritten, files holds the
    patient's own documents — photos, ID proofs, scanned consent, report PDFs.

    Without this, the surviving patient's document list silently omits
    everything uploaded before the merge, which is the same failure mode
    _repoint_visits exists to prevent.

    Raw SQL rather than importing FileRecord: that import would register the
    model on Base.metadata as a side effect, changing which tables the guard
    sees on branches that don't wire the files router. The table exists from
    0019 regardless.

    No uniqueness to collide with — a file belongs to one patient, so every
    source row simply moves.
    """
    await db.execute(
        text(
            "UPDATE files SET patient_id = :target_id WHERE patient_id = :source_id"
        ),
        {"target_id": target.id, "source_id": source.id},
    )
    await db.flush()


'''

ANCHOR = "async def _repoint_ot_schedules("
if "_repoint_files" not in text and ANCHOR in text:
    text = text.replace(ANCHOR, HELPER + ANCHOR, 1)
    print("+ added _repoint_files()")

# ------------------------------------------------------------- the call site
CALL = "    await _repoint_ot_schedules(db, source=source, target=target)"
if CALL in text and "_repoint_files(db, source=source" not in text:
    text = text.replace(
        CALL, CALL + "\n    await _repoint_files(db, source=source, target=target)", 1
    )
    print("+ wired into approve_merge")

if text != before:
    SVC.write_text(text)
    print("\nwrote backend/app/patients/service.py")
else:
    print("\nnothing changed")

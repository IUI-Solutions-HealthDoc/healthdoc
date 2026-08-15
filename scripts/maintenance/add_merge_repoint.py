#!/usr/bin/env python3
"""Add a table to patient-merge repointing.

    python3 scripts/maintenance/add_merge_repoint.py admissions "why it repoints"

Run from the repo root. Idempotent.

WHY THIS IS A TOOL AND NOT A ONE-OFF
------------------------------------
@priyanshuiuis's test_repointing_covers_every_patient_fk introspects
Base.metadata for every FK to patients.id and fails if approve_merge doesn't
handle it. It has now caught four pre-existing gaps in a week — orders and
prescriptions, fhir_bundle_transactions, files, admissions — each written by a
different person, each invisible until an unrelated PR happened to register
the model.

It will keep catching them, because the trigger is "someone imports a model
that was always there". So the fix is worth automating.

WHEN NOT TO USE THIS
--------------------
If the table is evidence *of the merge* rather than data *about the patient*,
it belongs in AUDIT_TABLES_EXEMPT_FROM_REPOINTING instead — repointing it
would rewrite the record of which patient merged into which. patient_merge_log
is the only one so far.

If a real decision is needed about conflict handling (a per-patient uniqueness
constraint the source and target could both violate), write the helper by hand
— patient_identifiers is that case.
"""
import pathlib
import re
import sys

if len(sys.argv) < 2:
    sys.exit(__doc__)

TABLE = sys.argv[1]
REASON = sys.argv[2] if len(sys.argv) > 2 else (
    f"{TABLE} belongs to the patient, so it follows them to the surviving record."
)

SVC = pathlib.Path("backend/app/patients/service.py")
if not SVC.exists():
    sys.exit("run me from the repo root")

text = SVC.read_text()
before = text
helper = f"_repoint_{TABLE}"

if helper in text and f'"{TABLE}"' in text:
    print(f"~ {TABLE} already repointed")
    sys.exit(0)

# ------------------------------------------------------------------ the set
m = re.search(r"REPOINTED_ON_MERGE: frozenset\[str\] = frozenset\(\s*\{([^}]*)\}\s*\)",
              text, re.S)
if not m:
    sys.exit("! REPOINTED_ON_MERGE not found in the expected shape")

if f'"{TABLE}"' in m.group(1):
    print(f"~ {TABLE} already in REPOINTED_ON_MERGE")
else:
    members = " ".join(m.group(1).split()).rstrip(",")
    text = text.replace(
        m.group(0),
        "REPOINTED_ON_MERGE: frozenset[str] = frozenset(\n"
        f"    {{{members}, \"{TABLE}\"}}\n"
        ")",
        1,
    )
    print(f"+ {TABLE} added to REPOINTED_ON_MERGE")

# --------------------------------------------------------------- the helper
HELPER = f'''async def {helper}(db: AsyncSession, *, source: Patient, target: Patient) -> None:
    """Moves source's {TABLE} rows onto target.

    {REASON}

    Surfaced by test_repointing_covers_every_patient_fk: the FK to patients.id
    was always there, and became visible to the guard when the model was
    registered on Base.metadata.

    Raw SQL rather than importing the model — that import would register it as
    a side effect, changing which tables the guard sees on branches that do not
    otherwise load it. The table exists in the database either way.
    """
    await db.execute(
        text(
            "UPDATE {TABLE} SET patient_id = :target_id WHERE patient_id = :source_id"
        ),
        {{"target_id": target.id, "source_id": source.id}},
    )
    await db.flush()


'''

ANCHOR = "async def _repoint_ot_schedules("
if helper not in text:
    if ANCHOR not in text:
        sys.exit("! could not find _repoint_ot_schedules to anchor the helper")
    text = text.replace(ANCHOR, HELPER + ANCHOR, 1)
    print(f"+ {helper}() added")

# ------------------------------------------------------------- the call site
CALL = "    await _repoint_ot_schedules(db, source=source, target=target)"
if f"{helper}(db, source=source" not in text:
    if CALL not in text:
        sys.exit("! could not find the _repoint_ot_schedules call in approve_merge")
    text = text.replace(CALL, CALL + f"\n    await {helper}(db, source=source, target=target)", 1)
    print("+ wired into approve_merge")

if text != before:
    SVC.write_text(text)
    print("\nwrote backend/app/patients/service.py")
else:
    print("\nnothing changed")

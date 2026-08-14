#!/usr/bin/env python3
"""Repoint fhir_bundle_transactions on patient merge.

Run from the repo root, on b3-w4-201-opd-fhir-stubs (#367). Idempotent.

WHY THIS EXISTS
---------------
#367's CI fails on test_repointing_covers_every_patient_fk:

    ['fhir_bundle_transactions'] have a foreign key to patients.id but are
    not in REPOINTED_ON_MERGE

That is not a defect in #367. It is Priyanshu's introspection guard doing
exactly what it was built for. 0026 gave fhir_bundle_transactions a
patient_id FK and never wired it into approve_merge; the table only became
visible to the guard when #367 registered the ORM model on Base.metadata.
The same guard is what surfaced orders and prescriptions being unrepointed
since 0008.

WHY REPOINT RATHER THAN EXEMPT
------------------------------
patient_merge_log is exempt because repointing it would erase the evidence
of which patient merged into which — the table's whole purpose is recording
the merge itself.

fhir_bundle_transactions is different. It records what was transmitted about
a person, and after a merge that person is the target. 0026's index is
(patient_id, transmitted_at), and its docstring says the query it serves is
"what was transmitted about this patient, and when — exactly the question a
DPDP access request asks." Leaving rows attached to the dead source id means
a DPDP access request against the surviving patient returns incomplete
transmission history. That is a compliance gap, not untidiness.

WHY RAW SQL RATHER THAN THE ORM MODEL
-------------------------------------
The other _repoint_* helpers import their model. This one cannot: the
FhirBundleTransaction model arrives with #367, and patients/service.py must
keep importing on branches that don't have it. The table exists from 0026
regardless of whether a model is registered, so a plain UPDATE is both
correct and independent of import order.
"""
import pathlib
import sys

SVC = pathlib.Path("backend/app/patients/service.py")
if not SVC.exists():
    sys.exit("run me from the repo root")

text = SVC.read_text()
before = text

# ------------------------------------------------------------------ the set
OLD_SET = ('REPOINTED_ON_MERGE: frozenset[str] = frozenset('
           '{"patient_identifiers", "visits", "ot_schedules"})')
NEW_SET = ('REPOINTED_ON_MERGE: frozenset[str] = frozenset(\n'
           '    {"patient_identifiers", "visits", "ot_schedules", "fhir_bundle_transactions"}\n'
           ')')

if '"fhir_bundle_transactions"' in text:
    print("~ already in REPOINTED_ON_MERGE")
elif OLD_SET in text:
    text = text.replace(OLD_SET, NEW_SET, 1)
    print("+ added fhir_bundle_transactions to REPOINTED_ON_MERGE")
else:
    sys.exit("! REPOINTED_ON_MERGE not in the expected shape — apply by hand")

# --------------------------------------------------------------- the helper
HELPER = '''

async def _repoint_fhir_bundle_transactions(
    db: AsyncSession, *, source: Patient, target: Patient
) -> None:
    """Moves source's ABDM transmission records onto target.

    0026 created fhir_bundle_transactions with a patient_id FK and no
    repointing logic; the guard test only saw it once #367 registered the
    ORM model. Repointed rather than exempted: unlike patient_merge_log,
    which must never be rewritten because it is the evidence of the merge,
    this table records what was transmitted *about a person*, and after a
    merge that person is the target.

    0026's index is (patient_id, transmitted_at) and exists to answer "what
    was transmitted about this patient, and when" — the question a DPDP
    access request asks. Rows left on the dead source id make that answer
    incomplete for the surviving patient.

    Raw SQL rather than the ORM model on purpose: FhirBundleTransaction
    arrives with #367, and this module has to keep importing on branches
    without it. The table exists from 0026 either way.

    No uniqueness to collide with — a transmission is a point-in-time fact,
    so every source row simply moves.
    """
    await db.execute(
        text(
            "UPDATE fhir_bundle_transactions SET patient_id = :target_id "
            "WHERE patient_id = :source_id"
        ),
        {"target_id": target.id, "source_id": source.id},
    )
    await db.flush()
'''

ANCHOR = "async def _repoint_ot_schedules("
if "_repoint_fhir_bundle_transactions" in text:
    print("~ helper already present")
elif ANCHOR in text:
    text = text.replace(ANCHOR, HELPER.lstrip("\n") + "\n\n" + ANCHOR, 1)
    print("+ added _repoint_fhir_bundle_transactions()")
else:
    sys.exit("! could not find _repoint_ot_schedules to anchor the helper")

# ------------------------------------------------------------- the call site
OLD_CALLS = "    await _repoint_ot_schedules(db, source=source, target=target)"
NEW_CALLS = (OLD_CALLS +
             "\n    await _repoint_fhir_bundle_transactions(db, source=source, target=target)")
if "_repoint_fhir_bundle_transactions(db, source=source" in text.split("async def _repoint")[0] + \
        "".join(text.split("approve_merge")[1:2]):
    print("~ call site already wired")
elif OLD_CALLS in text:
    text = text.replace(OLD_CALLS, NEW_CALLS, 1)
    print("+ wired into approve_merge")
else:
    sys.exit("! could not find the _repoint_ot_schedules call in approve_merge")

if "from sqlalchemy import" in text and "text" not in text.split("\n\n")[0]:
    pass  # `text` is already imported in this module for the UHID sequences

if text != before:
    SVC.write_text(text)
    print("\nwrote backend/app/patients/service.py")
else:
    print("\nnothing changed.")

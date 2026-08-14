#!/usr/bin/env python3
"""Add facility_id to the raw-SQL test seeds that predate 0021 and 0022.

    python3 fix_seed_facility_id.py encounters   # on b3-w3-180-doctor-queue (#351)
    python3 fix_seed_facility_id.py orders       # on b3-w3-181-order-creation (#352)

0021 adds encounters.facility_id NOT NULL; 0022 adds orders.facility_id NOT NULL.
Both migrations backfill correctly and both authors' application code populates the
column. What breaks is three test helpers that write these tables with raw SQL,
written when the column did not exist:

    backend/tests/_lab_seed.py
    backend/tests/billing/test_billing_flows.py
    backend/tests/files/test_0019_files_db.py

Split into two phases because orders.facility_id does not exist until 0022 — running
the orders phase on #351's branch would fail on a column that isn't there yet.

Run from the repo root. Idempotent.
"""
import sys
import pathlib

phase = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
if phase not in ("encounters", "orders"):
    sys.exit(__doc__)

LAB_SEED = pathlib.Path("backend/tests/_lab_seed.py")
BILLING = pathlib.Path("backend/tests/billing/test_billing_flows.py")
FILES = pathlib.Path("backend/tests/files/test_0019_files_db.py")
PHARMACY = pathlib.Path("backend/tests/pharmacy/conftest.py")

EDITS = {
    "encounters": [
        (LAB_SEED,
         '"INSERT INTO encounters (id, visit_id, provider_user_id, created_by) "\n'
         '                "VALUES (:id, :vid, :prov, :by) ON CONFLICT (id) DO NOTHING"),\n'
         '                {"id": ENCOUNTER_ID, "vid": VISIT_ID, "prov": creator, "by": creator})',
         '"INSERT INTO encounters (id, visit_id, facility_id, provider_user_id, created_by) "\n'
         '                "VALUES (:id, :vid, :fac, :prov, :by) ON CONFLICT (id) DO NOTHING"),\n'
         '                {"id": ENCOUNTER_ID, "vid": VISIT_ID, "fac": FACILITY_ID,\n'
         '                 "prov": creator, "by": creator})'),

        # The helper reads what it needs off the visit; facility_id joins that set
        # rather than becoming another parameter, so no call site changes.
        (BILLING,
         'sa.text("SELECT patient_id, created_by FROM visits WHERE id = :id"),',
         'sa.text("SELECT patient_id, facility_id, created_by FROM visits WHERE id = :id"),'),
        (BILLING,
         '    patient_id, actor_id = visit_row.patient_id, visit_row.created_by',
         '    patient_id, actor_id = visit_row.patient_id, visit_row.created_by\n'
         '    facility_id = visit_row.facility_id'),
        (BILLING,
         '            "INSERT INTO encounters (id, visit_id, provider_user_id, created_by) "\n'
         '            "VALUES (:id, :visit_id, :provider, :created_by)"\n'
         '        ),\n'
         '        {"id": encounter_id, "visit_id": visit_id,\n'
         '         "provider": actor_id, "created_by": actor_id},',
         '            "INSERT INTO encounters "\n'
         '            "(id, visit_id, facility_id, provider_user_id, created_by) "\n'
         '            "VALUES (:id, :visit_id, :facility_id, :provider, :created_by)"\n'
         '        ),\n'
         '        {"id": encounter_id, "visit_id": visit_id, "facility_id": facility_id,\n'
         '         "provider": actor_id, "created_by": actor_id},'),

        (FILES,
         '                    "INSERT INTO encounters (id, visit_id, provider_user_id, created_by) "\n'
         '                    "VALUES (:id, :visit_id, :provider, :created_by)"\n'
         '                ),\n'
         '                {"id": encounter_id, "visit_id": visit_id, "provider": user_id, "created_by": user_id},',
         '                    "INSERT INTO encounters "\n'
         '                    "(id, visit_id, facility_id, provider_user_id, created_by) "\n'
         '                    "VALUES (:id, :visit_id, :facility_id, :provider, :created_by)"\n'
         '                ),\n'
         '                {"id": encounter_id, "visit_id": visit_id, "facility_id": facility_id,\n'
         '                 "provider": user_id, "created_by": user_id},'),

        # Triple-quoted, which is why it matched neither of the greps that
        # caught the other three. facility_id is already a local here.
        (PHARMACY,
         "        INSERT INTO encounters (id, visit_id, provider_user_id, encounter_type, created_by)\n"
         "        VALUES (:id, :visit_id, :provider, 'consultation', :created_by)\n"
         '    """), {"id": encounter_id, "visit_id": visit_id, "provider": doctor_id, "created_by": doctor_id})',
         "        INSERT INTO encounters\n"
         "            (id, visit_id, facility_id, provider_user_id, encounter_type, created_by)\n"
         "        VALUES (:id, :visit_id, :facility_id, :provider, 'consultation', :created_by)\n"
         '    """), {"id": encounter_id, "visit_id": visit_id, "facility_id": facility_id,\n'
         '             "provider": doctor_id, "created_by": doctor_id})'),
    ],
    "orders": [
        (LAB_SEED,
         '"INSERT INTO orders (id, order_number, encounter_id, patient_id, order_type, "\n'
         '                " created_by) "\n'
         '                "VALUES (:id, \'ORD-LABTEST-0001\', :eid, :pid, \'lab\', :by) "\n'
         '                "ON CONFLICT (id) DO NOTHING"),\n'
         '                {"id": ORDER_ID, "eid": ENCOUNTER_ID, "pid": PATIENT_ID, "by": creator})',
         '"INSERT INTO orders (id, order_number, encounter_id, patient_id, order_type, "\n'
         '                " facility_id, created_by) "\n'
         '                "VALUES (:id, \'ORD-LABTEST-0001\', :eid, :pid, \'lab\', :fac, :by) "\n'
         '                "ON CONFLICT (id) DO NOTHING"),\n'
         '                {"id": ORDER_ID, "eid": ENCOUNTER_ID, "pid": PATIENT_ID,\n'
         '                 "fac": FACILITY_ID, "by": creator})'),

        (BILLING,
         '            "(id, encounter_id, order_number, patient_id, order_type, created_by) "\n'
         '            "VALUES (:id, :encounter_id, :order_number, :patient_id, \'lab\', :actor)"\n'
         '        ),\n'
         '        {"id": order_id, "encounter_id": encounter_id, "patient_id": patient_id,\n'
         '         "order_number": f"O{uuid.uuid4().hex[:10]}", "actor": actor_id},',
         '            "(id, encounter_id, order_number, patient_id, order_type, "\n'
         '            "facility_id, created_by) "\n'
         '            "VALUES (:id, :encounter_id, :order_number, :patient_id, \'lab\', "\n'
         '            ":facility_id, :actor)"\n'
         '        ),\n'
         '        {"id": order_id, "encounter_id": encounter_id, "patient_id": patient_id,\n'
         '         "order_number": f"O{uuid.uuid4().hex[:10]}", "facility_id": facility_id,\n'
         '         "actor": actor_id},'),

        (FILES,
         '                    "(id, order_number, encounter_id, patient_id, order_type, created_by) "\n'
         '                    "VALUES (:id, :num, :encounter_id, :patient_id, \'lab\', :created_by)"\n'
         '                ),\n'
         '                {"id": order_id, "num": f"O{uuid.uuid4().hex[:10]}", "encounter_id": encounter_id,\n'
         '                 "patient_id": patient_id, "created_by": user_id},',
         '                    "(id, order_number, encounter_id, patient_id, order_type, "\n'
         '                    "facility_id, created_by) "\n'
         '                    "VALUES (:id, :num, :encounter_id, :patient_id, \'lab\', "\n'
         '                    ":facility_id, :created_by)"\n'
         '                ),\n'
         '                {"id": order_id, "num": f"O{uuid.uuid4().hex[:10]}", "encounter_id": encounter_id,\n'
         '                 "patient_id": patient_id, "facility_id": facility_id,\n'
         '                 "created_by": user_id},'),
    ],
}

applied = skipped = missing = 0
for path, old, new in EDITS[phase]:
    if not path.exists():
        print(f"! {path} does not exist on this branch")
        missing += 1
        continue
    text = path.read_text()
    if new in text:
        print(f"~ {path.name}: already applied")
        skipped += 1
    elif old in text:
        path.write_text(text.replace(old, new, 1))
        print(f"+ {path.name}: patched")
        applied += 1
    else:
        print(f"! {path.name}: pattern not found — the file has changed, fix by hand")
        missing += 1

print(f"\n{phase}: {applied} patched, {skipped} already done, {missing} needing attention")
sys.exit(1 if missing else 0)

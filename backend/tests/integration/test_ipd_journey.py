"""tests/integration/test_ipd_journey.py

#243 (BB-W7-01) - IPD core journey:
admission -> transfer -> discharge.

Mirrors tests/integration/test_opd_journey.py's shape: real HTTP calls
against real Postgres, state (visit_id, admission_id, ...) carried from
one step to the next.

ASSUMPTIONS FLAGGED (check these before trusting a green run):
1. TRANSFER ENDPOINT - guessed as PUT /api/v1/admissions/{id}/transfer.
   Confirm the real path in app/admissions/router.py and fix TRANSFER_PATH
   below if it's different.
2. RESPONSE SHAPE - assumes resp.json()["id"] directly (like
   test_opd_journey.py), not resp.json()["data"]["id"] (like your
   pathology/radiology tests). Confirm and fix if needed.
"""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from tests._lab_seed import TEST_DATABASE_URL
from tests.integration.conftest import (
    DOCTOR,
    RECEPTIONIST,
    TEST_DEPARTMENT_ID,
    TEST_FACILITY_ID,
)

WARD_A_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
WARD_B_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a2")
BED_A_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
BED_B_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b2")

# ASSUMPTION #1 - fix this after checking app/admissions/router.py
TRANSFER_PATH = "/api/v1/admissions/{admission_id}/transfer"


async def _seed_wards_and_beds() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text(
                "INSERT INTO wards (id, name, department_id, facility_id, is_active) "
                "VALUES (:id, :name, :dept, :fac, true) "
                "ON CONFLICT (id) DO NOTHING"),
                {"id": WARD_A_ID, "name": "IPD Journey Ward A",
                 "dept": TEST_DEPARTMENT_ID, "fac": TEST_FACILITY_ID})
            await conn.execute(sa.text(
                "INSERT INTO wards (id, name, department_id, facility_id, is_active) "
                "VALUES (:id, :name, :dept, :fac, true) "
                "ON CONFLICT (id) DO NOTHING"),
                {"id": WARD_B_ID, "name": "IPD Journey Ward B",
                 "dept": TEST_DEPARTMENT_ID, "fac": TEST_FACILITY_ID})
            await conn.execute(sa.text(
                "INSERT INTO beds (id, ward_id, bed_number, status) "
                "VALUES (:id, :ward, 'A-01', 'vacant') "
                "ON CONFLICT (id) DO NOTHING"),
                {"id": BED_A_ID, "ward": WARD_A_ID})
            await conn.execute(sa.text(
                "INSERT INTO beds (id, ward_id, bed_number, status) "
                "VALUES (:id, :ward, 'B-01', 'vacant') "
                "ON CONFLICT (id) DO NOTHING"),
                {"id": BED_B_ID, "ward": WARD_B_ID})

            # Clear any admission this journey left behind on a previous run.
            #
            # The beds have fixed ids, and 0034 enforces one active admission per
            # bed — so the second run of this test got "409 Bed is already
            # occupied" from its own last pass. That 409 is the constraint working
            # exactly as intended; it is the test that was not re-runnable.
            #
            # Deliberately scoped to this journey's two beds. A blanket DELETE FROM
            # admissions would take out other suites' data in a shared test DB.
            # Children first: discharges, patient_movement_log and
            # discharge_notifications all FK to admissions with ondelete=RESTRICT,
            # and 0023's vitals can hang off an admission too. RESTRICT is correct
            # for a clinical record — a discharge summary must not vanish because
            # someone deleted the admission — it just means test cleanup has to
            # unwind in dependency order.
            beds = {"bed_a": BED_A_ID, "bed_b": BED_B_ID}
            admissions_here = (
                "SELECT id FROM admissions WHERE bed_id IN (:bed_a, :bed_b)")

            # discharge_notifications hangs off discharges (discharge_id), not off
            # admissions — so it has to go before discharges, two levels down.
            await conn.execute(sa.text(
                "DELETE FROM discharge_notifications WHERE discharge_id IN "
                f"(SELECT id FROM discharges WHERE admission_id IN ({admissions_here}))"),
                beds)

            for table in ("discharges", "patient_movement_log",
                          "intake_output_records", "vitals"):
                await conn.execute(sa.text(
                    f"DELETE FROM {table} WHERE admission_id IN ({admissions_here})"),
                    beds)

            await conn.execute(sa.text(
                "DELETE FROM admissions WHERE bed_id IN (:bed_a, :bed_b)"),
                {"bed_a": BED_A_ID, "bed_b": BED_B_ID})
            await conn.execute(sa.text(
                "UPDATE beds SET status = 'vacant' WHERE id IN (:bed_a, :bed_b)"),
                {"bed_a": BED_A_ID, "bed_b": BED_B_ID})
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def seeded_wards_and_beds() -> None:
    import asyncio
    asyncio.run(_seed_wards_and_beds())


class TestIPDCoreJourney:
    # xfail removed. The reason recorded here — "POST /api/v1/admissions has no
    # registered route at all ... app/admissions/ only has models.py" — was true
    # when written and is not any more: #216 added the router, and app/ipd/router.py
    # re-exports it because MODULES gates on "ipd", not "admissions".
    #
    # Worth knowing why that was so easy to get wrong twice (this xfail, and my own
    # review comment on #216): main.py used to catch ModuleNotFoundError around the
    # whole import and log "has no router.py yet", so a router that existed but
    # failed to import — or one loaded under a different module name — looked
    # identical to one that had never been written. That now raises instead.
    def test_full_ipd_journey_admission_to_discharge(
        self, client_as, seeded_patient_id, seeded_wards_and_beds
    ):
        patient_id = seeded_patient_id
        doctor_id = str(uuid.uuid5(uuid.NAMESPACE_OID, DOCTOR.sub))

        # Step 1: create an IPD visit
        client = client_as(RECEPTIONIST)
        visit_resp = client.post( 
            "/api/v1/visits",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "patient_id": patient_id,
                "created_by": str(uuid.uuid5(uuid.NAMESPACE_OID, RECEPTIONIST.sub)),
                "facility_id": str(TEST_FACILITY_ID),
                "department_id": str(TEST_DEPARTMENT_ID),
                "visit_type": "ipd",
                "visit_date": "2026-08-12T09:00:00Z",
            },
        )
        assert visit_resp.status_code == 201, visit_resp.text
        # EnvelopeMiddleware wraps every response as {success, data, error, meta},
        # so the payload is under "data" — same as the OPD journey does. Noted as
        # assumption 2 in this module's docstring; now confirmed against a running
        # app rather than assumed.
        visit_id = visit_resp.json()["data"]["id"]

        # Step 2: admit the patient
        client = client_as(DOCTOR)
        admission_resp = client.post(
            "/api/v1/admissions",
            json={
                "visit_id": visit_id,
                "patient_id": patient_id,
                "ward_id": str(WARD_A_ID),
                "bed_id": str(BED_A_ID),
                "admitted_at": "2026-08-12T09:30:00Z",
                "reason": "Journey test admission",
            },
        )
        assert admission_resp.status_code == 201, admission_resp.text
        admission = admission_resp.json()["data"]
        admission_id = admission["id"]
        assert admission["status"] == "admitted"

        # Step 3: transfer. Enabled now that the routes are confirmed against a
        # running app — POST, not PUT, and there is no separate /discharges
        # collection; both hang off the admission.
        transfer_resp = client.post(
            TRANSFER_PATH.format(admission_id=admission_id),
            json={
                "to_ward_id": str(WARD_B_ID),
                "to_bed_id": str(BED_B_ID),
                "reason": "Journey test transfer",
                "moved_by": doctor_id,
            },
        )
        assert transfer_resp.status_code in (200, 201), transfer_resp.text

        # 0034 enforces one active admission per bed, so a transfer that failed to
        # release the old bed would make the next admission there impossible.
        assert transfer_resp.json()["data"]["bed_id"] == str(BED_B_ID)

        # Step 4: discharge.
        discharge_resp = client.post(
            f"/api/v1/admissions/{admission_id}/discharge",
            json={
                "discharged_at": "2026-08-13T11:00:00Z",
                "discharge_type": "discharged",
                "discharge_summary": "Journey test discharge - no complications.",
            },
        )
        assert discharge_resp.status_code in (200, 201), discharge_resp.text

        # The endpoint returns the discharge record (DischargeOut), not the
        # admission — so assert on what it actually returns, then read the
        # admission back to confirm it really transitioned. The second check is
        # the one that matters: a discharge row written without closing the
        # admission would leave bed B occupied forever under 0034.
        discharge = discharge_resp.json()["data"]
        assert discharge["admission_id"] == admission_id
        assert discharge["discharge_type"] == "discharged"

        after = client.get(f"/api/v1/admissions/{admission_id}")
        assert after.status_code == 200, after.text
        assert after.json()["data"]["status"] == "discharged"

        # Step 5: the discharge summary must be retrievable afterwards — it is the
        # document the patient leaves with and the FHIR DischargeSummary source.
        summary_resp = client.get(f"/api/v1/admissions/{admission_id}/discharge-summary")
        assert summary_resp.status_code == 200, summary_resp.text
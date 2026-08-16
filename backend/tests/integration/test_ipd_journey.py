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
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def seeded_wards_and_beds() -> None:
    import asyncio
    asyncio.run(_seed_wards_and_beds())


class TestIPDCoreJourney:
    @pytest.mark.xfail(
        reason="visit_number_counters bug is now fixed (migration 0035), so "
               "Step 1 (visit creation) now passes. Blocked at Step 2: "
               "POST /api/v1/admissions has no registered route at all — "
               "confirmed via full route dump "
               "(python -c \"from app.main import app; "
               "[print(r.path) for r in app.routes]\" | grep admission "
               "returns nothing). app/admissions/ only has models.py, no "
               "router.py exists. This is a missing feature, not a schema "
               "bug — someone needs to build the admissions router before "
               "this journey can progress further.",
        strict=False,
    )
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
        visit_id = visit_resp.json()["id"]

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
        admission = admission_resp.json()
        admission_id = admission["id"]
        assert admission["status"] == "admitted"

        # Step 3 (temporarily commented out — see instructions)
        # transfer_resp = client.put(
        #     TRANSFER_PATH.format(admission_id=admission_id),
        #     json={
        #         "to_ward_id": str(WARD_B_ID),
        #         "to_bed_id": str(BED_B_ID),
        #         "reason": "Journey test transfer",
        #         "moved_by": doctor_id,
        #     },
        # )
        # assert transfer_resp.status_code in (200, 201), (
        #     f"Transfer failed ({transfer_resp.status_code}): {transfer_resp.text}. "
        #     f"Check TRANSFER_PATH against app/admissions/router.py."
        # )

        # Step 4 (temporarily commented out — see instructions)
        # discharge_resp = client.post(
        #     "/api/v1/discharges",
        #     json={
        #         "admission_id": admission_id,
        #         "discharged_at": "2026-08-13T11:00:00Z",
        #         "discharge_type": "discharged",
        #         "discharge_summary": "Journey test discharge - no complications.",
        #     },
        # )
        # assert discharge_resp.status_code == 201, discharge_resp.text
        # discharge = discharge_resp.json()
        # assert discharge["admission_id"] == admission_id

        print("ADMISSION RESPONSE:", admission)
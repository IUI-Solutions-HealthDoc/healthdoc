"""A real PostgreSQL contention gate, not two sequential SQLite calls."""
import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.admissions.models import Admission, Bed, Ward
from app.nursing.models import MedicationAdministration
from app.nursing.schemas import MedicationAdministrationCreate
from app.nursing.service import record_administration
from app.opd.models import Encounter, Visit
from app.orders.models import Prescription, PrescriptionItem
from app.patients.models import Patient
from app.users.models import Facility, User


@pytest.mark.asyncio
async def test_second_nurse_waits_for_first_commit_then_refuses_duplicate_dose():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires explicit TEST_DATABASE_URL; no application DB fallback")
    engine = create_async_engine(url)
    assert "test" in (engine.url.database or "").lower(), "Dedicated test database required"
    Session = async_sessionmaker(engine, expire_on_commit=False)
    ids = {name: uuid.uuid4() for name in ("facility", "nurse1", "nurse2", "patient", "visit",
                                         "ward", "bed", "admission", "encounter", "prescription", "item")}
    now = datetime.now(UTC)
    second = None
    try:
        async with Session.begin() as db:
            rows = [
                Facility(id=ids["facility"], code="EM" + uuid.uuid4().hex[:8], name="Synthetic eMAR test", state_code="TS"),
                *[User(id=ids[name], facility_id=ids["facility"], keycloak_sub=str(ids[name]),
                       username="test-" + ids[name].hex[:10], full_name="Synthetic nurse")
                  for name in ("nurse1", "nurse2")],
                Patient(id=ids["patient"], facility_id=ids["facility"], uhid="TEST-" + ids["patient"].hex[:10],
                        full_name="Synthetic eMAR patient", sex="unknown", age_years=30,
                        identity_path="demographics_only", created_by=ids["nurse1"]),
                Visit(id=ids["visit"], facility_id=ids["facility"], patient_id=ids["patient"],
                      visit_number="TEST-" + ids["visit"].hex[:10], visit_type="ipd", visit_date=now,
                      created_by=ids["nurse1"]),
                Ward(id=ids["ward"], facility_id=ids["facility"], name="Synthetic ward"),
                Bed(id=ids["bed"], ward_id=ids["ward"], bed_number="TEST", status="occupied"),
                Admission(id=ids["admission"], visit_id=ids["visit"], patient_id=ids["patient"],
                          ward_id=ids["ward"], bed_id=ids["bed"], admitted_at=now, created_by=ids["nurse1"]),
                Encounter(id=ids["encounter"], visit_id=ids["visit"], facility_id=ids["facility"],
                          provider_user_id=ids["nurse1"], created_by=ids["nurse1"]),
                Prescription(id=ids["prescription"], encounter_id=ids["encounter"],
                             facility_id=ids["facility"], patient_id=ids["patient"], created_by=ids["nurse1"]),
                PrescriptionItem(id=ids["item"], prescription_id=ids["prescription"],
                                 medicine_name="Synthetic test medicine", dosage="Recorded dose"),
            ]
            for row in rows:
                db.add(row)
                await db.flush()  # Explicit FK order, including audited actors.

        payload = MedicationAdministrationCreate(
            prescription_item_id=ids["item"], admission_id=ids["admission"], patient_id=ids["patient"],
            status="given", scheduled_at=now,
        )
        started = asyncio.Event()
        async def second_nurse():
            async with Session.begin() as db:
                started.set()
                try:
                    await record_administration(db, payload, recorded_by=ids["nurse2"])
                    return "duplicate-written"
                except HTTPException as exc:
                    assert exc.status_code == 409
                    return "refused"

        async with Session.begin() as first:
            await record_administration(first, payload, recorded_by=ids["nurse1"])
            second = asyncio.create_task(second_nurse())
            await started.wait()
            with pytest.raises(TimeoutError):
                # The first write is uncommitted. Without item locking the
                # second session sees no dose and writes another one.
                await asyncio.wait_for(asyncio.shield(second), timeout=0.25)
        assert await asyncio.wait_for(second, timeout=10) == "refused"
        async with Session() as db:
            count = await db.scalar(select(func.count()).select_from(MedicationAdministration).where(
                MedicationAdministration.prescription_item_id == ids["item"]))
            assert count == 1
    finally:
        if second is not None and not second.done():
            second.cancel()
            await asyncio.gather(second, return_exceptions=True)
        # Synthetic rows stay in the disposable test DB; do not delete around
        # the append-only audit chain to make fixtures cosmetically disappear.
        await engine.dispose()

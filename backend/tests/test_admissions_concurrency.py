"""tests/test_admissions_concurrency.py

Proves admit_patient is race-safe against real Postgres (SQLite has no
row locking and its IntegrityError carries no sqlstate, so the main
suite can't test this -- see test_bed_occupancy.py's
test_admit_patient_catches_race_condition for what that gap looks like).
Auto-skips if the real DB isn't reachable. Matches
test_queue_counters_concurrency.py's pattern.
"""
import asyncio
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.admissions import service
from app.admissions.models import Admission, Bed, Ward
from app.common.config import get_settings
from app.opd.models import Visit
from app.patients.models import Patient
from app.users.models import Facility

pytestmark = pytest.mark.asyncio


async def _real_database_is_ready() -> bool:
    try:
        engine = create_async_engine(get_settings().database_url)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT to_regclass('public.admissions')"))
            exists = result.scalar() is not None
        await engine.dispose()
        return exists
    except Exception:
        return False


async def test_concurrent_admission_never_double_books_bed():
    if not await _real_database_is_ready():
        pytest.skip("Real Postgres unreachable or admissions missing -- will auto-run once ready.")

    engine = create_async_engine(get_settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    facility_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    ward_id = uuid.uuid4()
    bed_id = uuid.uuid4()
    visit_id_a = uuid.uuid4()
    visit_id_b = uuid.uuid4()

    async with Session() as setup:
        setup.add(Facility(id=facility_id, code=f"CONC{uuid.uuid4().hex[:4]}", name="Concurrency Test", state_code="TS"))
        await setup.commit()
    async with Session() as setup:
        setup.add(Patient(
            id=patient_id, uhid=f"UHID{uuid.uuid4().hex[:8]}", full_name="Concurrency Patient",
            sex="male", dob=date(1990, 1, 1), facility_id=facility_id,
            identity_path="demographics_only", identity_status="verified",
            created_by=uuid.uuid4(),
        ))
        await setup.commit()
    async with Session() as setup:
        setup.add(Ward(id=ward_id, name="Concurrency Ward", facility_id=facility_id))
        setup.add(Bed(id=bed_id, ward_id=ward_id, bed_number="C1", status="vacant"))
        await setup.commit()
    async with Session() as setup:
        setup.add(Visit(
            id=visit_id_a, visit_number=f"V{uuid.uuid4().hex[:8]}", patient_id=patient_id,
            facility_id=facility_id, visit_type="ipd", visit_date=datetime.now(timezone.utc),
            created_by=uuid.uuid4(),
        ))
        setup.add(Visit(
            id=visit_id_b, visit_number=f"V{uuid.uuid4().hex[:8]}", patient_id=patient_id,
            facility_id=facility_id, visit_type="ipd", visit_date=datetime.now(timezone.utc),
            created_by=uuid.uuid4(),
        ))
        await setup.commit()

    async def admit_in_own_session(visit_id: uuid.UUID):
        async with Session() as session:
            try:
                async with session.begin():
                    await service.admit_patient(
                        session, visit_id=visit_id, ward_id=ward_id, bed_id=bed_id, created_by=uuid.uuid4(),
                    )
                return "admitted"
            except service.BedNotAvailable:
                # The failed flush inside admit_patient left this
                # transaction aborted on Postgres -- session.begin()'s
                # own __aexit__ already rolled it back when the
                # exception propagated out of the `async with` block
                # above, so nothing further to clean up here.
                return "rejected"

    try:
        results = await asyncio.gather(
            admit_in_own_session(visit_id_a),
            admit_in_own_session(visit_id_b),
        )

        # Exactly one succeeds, the other gets a clean rejection -- not
        # both succeeding (a double booking) and not a raw 500.
        assert sorted(results) == ["admitted", "rejected"]

        async with Session() as check:
            count_result = await check.execute(
                Admission.__table__.select().where(
                    Admission.bed_id == bed_id, Admission.status == "admitted"
                )
            )
            admitted_rows = count_result.fetchall()
            assert len(admitted_rows) == 1
    finally:
        async with Session() as cleanup:
            await cleanup.execute(Admission.__table__.delete().where(Admission.bed_id == bed_id))
            await cleanup.execute(Visit.__table__.delete().where(Visit.patient_id == patient_id))
            await cleanup.execute(Bed.__table__.delete().where(Bed.id == bed_id))
            await cleanup.execute(Ward.__table__.delete().where(Ward.id == ward_id))
            await cleanup.execute(Patient.__table__.delete().where(Patient.id == patient_id))
            await cleanup.execute(Facility.__table__.delete().where(Facility.id == facility_id))
            await cleanup.commit()

    await engine.dispose()

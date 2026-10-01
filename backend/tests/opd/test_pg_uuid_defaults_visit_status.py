"""Migration 0089 on real PostgreSQL: id defaults and the widened visit status CHECK.

The SQLite fixture builds tables from the models, which already carry both, so
only a migrated PostgreSQL database can show that the schema agrees with them.
"""

import importlib
import os
import uuid
from datetime import date

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.appointments.models import Appointment, AppointmentService
from app.emergency.service import get_emergency_worklist
from tests.billing.conftest import seed_facility, seed_patient, seed_user, seed_visit

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
migration = importlib.import_module("migrations.versions.0089_uuid_pk_defaults_visit_status")


@pytest_asyncio.fixture
async def pg() -> AsyncSession:
    if not TEST_DATABASE_URL:
        pytest.skip("needs real PostgreSQL — run `make test-pg` from the repo root")
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    connection = await engine.connect()
    outer = await connection.begin()
    session = async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )()
    try:
        yield session
    finally:
        await session.close()
        await outer.rollback()
        await connection.close()
        await engine.dispose()


async def _seed_department(db: AsyncSession, facility_id: uuid.UUID) -> uuid.UUID:
    department_id = uuid.uuid4()
    await db.execute(
        sa.text(
            "INSERT INTO departments (id, facility_id, code, name) "
            "VALUES (:id, :facility_id, :code, 'Migration Test Dept')"
        ),
        {"id": department_id, "facility_id": facility_id, "code": f"M{department_id.hex[:6]}"},
    )
    return department_id


async def test_every_uuidpk_table_has_an_id_default(pg):
    rows = (
        await pg.execute(
            sa.text(
                "SELECT table_name, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'id' "
                "AND table_name = ANY(:tables)"
            ),
            {"tables": list(migration._TABLES)},
        )
    ).all()
    assert {name for name, _ in rows} == set(migration._TABLES)
    for name, default in rows:
        assert default == "uuid_generate_v4()", name


async def test_orm_inserts_appointment_service_and_appointment_without_an_id(pg):
    facility_id = await seed_facility(pg)
    user_id = await seed_user(pg, facility_id=facility_id)
    patient_id = await seed_patient(pg, facility_id=facility_id, created_by=user_id)
    department_id = await _seed_department(pg, facility_id)

    service = AppointmentService(facility_id=facility_id, name="Dressing change", duration_minutes=15)
    pg.add(service)
    await pg.flush()
    appointment = Appointment(
        facility_id=facility_id,
        patient_id=patient_id,
        department_id=department_id,
        service_id=service.id,
        service_name=service.name,
        duration_minutes=15,
        appointment_date=date(2026, 10, 1),
        start_time="10:00",
        end_time="10:15",
        created_by=user_id,
    )
    pg.add(appointment)
    await pg.flush()

    assert isinstance(service.id, uuid.UUID)
    assert isinstance(appointment.id, uuid.UUID)


@pytest.mark.parametrize("status", ["in_consultation", "closed", "registered", "lwbs"])
async def test_visit_status_check_accepts_the_values_the_code_writes(pg, status):
    facility_id = await seed_facility(pg)
    patient_id = await seed_patient(pg, facility_id=facility_id)
    visit_id = await seed_visit(pg, facility_id=facility_id, patient_id=patient_id)

    await pg.execute(
        sa.text("UPDATE visits SET status = :status WHERE id = :id"), {"status": status, "id": visit_id}
    )
    stored = await pg.scalar(sa.text("SELECT status FROM visits WHERE id = :id"), {"id": visit_id})
    assert stored == status


async def test_visit_status_check_still_rejects_unknown_values(pg):
    facility_id = await seed_facility(pg)
    patient_id = await seed_patient(pg, facility_id=facility_id)
    visit_id = await seed_visit(pg, facility_id=facility_id, patient_id=patient_id)

    with pytest.raises(IntegrityError, match="ck_visits_ck_visits_status"):
        async with pg.begin_nested():
            await pg.execute(
                sa.text("UPDATE visits SET status = 'active' WHERE id = :id"), {"id": visit_id}
            )


async def test_emergency_worklist_lists_a_new_arrival(pg):
    facility_id = await seed_facility(pg)
    user_id = await seed_user(pg, facility_id=facility_id)
    patient_id = await seed_patient(pg, facility_id=facility_id, created_by=user_id)
    visit_id = uuid.uuid4()
    await pg.execute(
        sa.text(
            "INSERT INTO visits (id, facility_id, patient_id, visit_type, status, "
            " visit_number, visit_date, created_by) "
            "VALUES (:id, :facility_id, :patient_id, 'emergency', 'registered', "
            "        :number, now(), :created_by)"
        ),
        {
            "id": visit_id, "facility_id": facility_id, "patient_id": patient_id,
            "number": f"E{visit_id.hex[:10]}", "created_by": user_id,
        },
    )

    worklist = await get_emergency_worklist(pg, facility_id)

    assert [item["visit_id"] for item in worklist] == [visit_id]

"""Tests for migration/module 0017 (ot_schedules, ot_records) -- B3-W1-02 (#137)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from app.ot.models import OtSchedule, OtRecord
from app.opd.models import Visit
from app.patients.models import Patient


@pytest_asyncio.fixture
async def fake_patient(db_session, fake_facility, fake_user_row):
    patient = Patient(
        full_name="Test Patient",
        sex="male",
        identity_path="thid_only",
        facility_id=fake_facility.id,
        created_by=fake_user_row.id,
    )
    db_session.add(patient)
    await db_session.flush()
    await db_session.refresh(patient)
    return patient


@pytest_asyncio.fixture
async def fake_visit(db_session, fake_facility, fake_patient, fake_user_row):
    visit = Visit(
        visit_number=f"VST-TST-{uuid.uuid4().hex[:8]}",
        patient_id=fake_patient.id,
        facility_id=fake_facility.id,
        visit_type="opd",
        visit_date=datetime.now(timezone.utc),
        created_by=fake_user_row.id,
    )
    db_session.add(visit)
    await db_session.flush()
    await db_session.refresh(visit)
    return visit


def test_ot_tables_registered_on_base_metadata():
    from app.common.db import Base

    assert "ot_schedules" in Base.metadata.tables
    assert "ot_records" in Base.metadata.tables


@pytest.mark.asyncio
async def test_ot_schedule_and_record_insert(
    db_session, fake_visit, fake_patient, fake_user_row
):
    schedule = OtSchedule(
        visit_id=fake_visit.id,
        patient_id=fake_patient.id,
        scheduled_start=datetime.now(timezone.utc),
        scheduled_end=datetime.now(timezone.utc) + timedelta(hours=1),
        procedure_name="Appendectomy",
        status="scheduled",
        created_by=fake_user_row.id,
    )
    db_session.add(schedule)
    await db_session.flush()
    await db_session.refresh(schedule)
    assert schedule.id is not None
    assert schedule.status == "scheduled"

    record = OtRecord(
        ot_schedule_id=schedule.id,
        surgeon_user_id=fake_user_row.id,
    )
    db_session.add(record)
    await db_session.flush()
    await db_session.refresh(record)
    assert record.id is not None
    assert record.ot_schedule_id == schedule.id


@pytest.mark.asyncio
async def test_ot_schedules_status_check_constraint(
    db_session, fake_visit, fake_patient, fake_user_row
):
    bad_schedule = OtSchedule(
        visit_id=fake_visit.id,
        patient_id=fake_patient.id,
        scheduled_start=datetime.now(timezone.utc),
        scheduled_end=datetime.now(timezone.utc) + timedelta(hours=1),
        procedure_name="Appendectomy",
        status="in_progress",
        created_by=fake_user_row.id,
    )
    db_session.add(bad_schedule)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_ot_record_requires_valid_schedule_fk(db_session, fake_user_row):
    bad_record = OtRecord(
        ot_schedule_id=uuid.uuid4(),
        surgeon_user_id=fake_user_row.id,
    )
    db_session.add(bad_record)
    with pytest.raises(IntegrityError):
        await db_session.flush()

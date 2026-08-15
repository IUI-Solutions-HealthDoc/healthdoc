"""Tests for HOD dashboard overview -- combines existing
list_queue_tokens() and list_roster() into one summary. Tested directly
against the service layer, no HTTP/JWT needed.
"""
import uuid
from datetime import date

import pytest

from app.departments.models import Department
from app.queue import service
from app.queue.models import Queue
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def _make_facility_and_department(db):
    facility_id = uuid.uuid4()
    department_id = uuid.uuid4()
    db.add(Facility(id=facility_id, code=f"F{uuid.uuid4().hex[:4]}", name="Test Facility", state_code="TS"))
    db.add(Department(id=department_id, code=f"D{uuid.uuid4().hex[:4]}", name="Test Dept", facility_id=facility_id))
    await db.flush()
    return facility_id, department_id


async def test_overview_combines_queues_and_roster(db):
    facility_id, department_id = await _make_facility_and_department(db)
    doctor_id = uuid.uuid4()
    today = date.today()

    db.add(User(
        id=doctor_id, keycloak_sub=f"doc-{uuid.uuid4()}", username=f"doc{uuid.uuid4().hex[:6]}",
        full_name="Dr. Overview", facility_id=facility_id,
    ))
    await db.flush()

    queue = Queue(
        id=uuid.uuid4(), facility_id=facility_id, department_id=department_id,
        doctor_user_id=doctor_id, service_date=today, is_open=True,
    )
    db.add(queue)
    await db.flush()

    await service.create_roster_entry(
        db, doctor_id, department_id, None, "morning", today,
        facility_id, ["admin"], None,
    )

    overview = await service.get_hod_dashboard_overview(db, department_id, today, facility_id)

    assert overview["department_id"] == department_id
    assert overview["date"] == today
    assert len(overview["queues"]) == 1
    assert overview["queues"][0]["doctor_name"] == "Dr. Overview"
    assert overview["queues"][0]["is_open"] is True
    assert len(overview["roster"]) == 1
    assert overview["roster"][0]["staff_user_id"] == doctor_id


async def test_overview_empty_when_nothing_scheduled(db):
    facility_id, department_id = await _make_facility_and_department(db)
    overview = await service.get_hod_dashboard_overview(db, department_id, date.today(), facility_id)
    assert overview["queues"] == []
    assert overview["roster"] == []


async def test_overview_rejects_wrong_facility(db):
    facility_id, department_id = await _make_facility_and_department(db)
    other_facility_id = uuid.uuid4()

    with pytest.raises(Exception) as exc_info:
        await service.get_hod_dashboard_overview(db, department_id, date.today(), other_facility_id)
    assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()

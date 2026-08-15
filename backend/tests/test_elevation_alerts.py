"""Tests for task 8's priority-elevation abuse detection (HOD dashboard
alerts). Tested directly against the service layer, no HTTP/JWT needed.
"""
import uuid
from datetime import date, datetime, timezone

import pytest

from app.common.enums import QueuePriority, QueueTokenStatus
from app.departments.models import Department
from app.queue import service
from app.queue.models import Queue, QueueToken, QueueTokenPriorityChange
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def _make_facility_and_department(db):
    facility_id = uuid.uuid4()
    department_id = uuid.uuid4()
    db.add(Facility(id=facility_id, code=f"F{uuid.uuid4().hex[:4]}", name="Test Facility", state_code="TS"))
    db.add(Department(id=department_id, code=f"D{uuid.uuid4().hex[:4]}", name="Test Dept", facility_id=facility_id))
    await db.flush()
    return facility_id, department_id


async def _make_queue_and_token(db, facility_id, department_id):
    queue = Queue(
        id=uuid.uuid4(), facility_id=facility_id, department_id=department_id,
        doctor_user_id=uuid.uuid4(), service_date=date.today(), is_open=True,
    )
    db.add(queue)
    await db.flush()

    token = QueueToken(
        id=uuid.uuid4(), facility_id=facility_id, queue_id=queue.id,
        visit_id=uuid.uuid4(), sequence=1, token_display="MED-001",
        initial_priority=QueuePriority.NORMAL.value, status=QueueTokenStatus.WAITING.value,
        priority=QueuePriority.NORMAL.value, priority_rank=6,
    )
    db.add(token)
    await db.flush()
    return token


async def _add_priority_change(db, token_id, changed_by, when):
    db.add(QueueTokenPriorityChange(
        id=uuid.uuid4(), queue_token_id=token_id,
        from_priority=QueuePriority.NORMAL.value, to_priority=QueuePriority.EMERGENCY.value,
        reason="test elevation reason here", changed_by=changed_by, changed_at=when,
    ))


async def test_flags_user_over_threshold(db):
    facility_id, department_id = await _make_facility_and_department(db)
    token = await _make_queue_and_token(db, facility_id, department_id)
    heavy_user = uuid.uuid4()
    db.add(User(
        id=heavy_user, keycloak_sub=f"sub-{uuid.uuid4()}", username=f"u{uuid.uuid4().hex[:6]}",
        full_name="Dr. Frequent", facility_id=facility_id,
    ))
    today = date.today()
    now = datetime.now(timezone.utc)

    for _ in range(6):  # over the threshold of 5
        await _add_priority_change(db, token.id, heavy_user, now)
    await db.flush()

    alerts = await service.get_priority_elevation_alerts(db, department_id, today, facility_id)

    assert len(alerts) == 1
    assert alerts[0]["user_id"] == heavy_user
    assert alerts[0]["elevation_count"] == 6
    assert alerts[0]["user_name"] == "Dr. Frequent"


async def test_does_not_flag_user_at_or_under_threshold(db):
    facility_id, department_id = await _make_facility_and_department(db)
    token = await _make_queue_and_token(db, facility_id, department_id)
    normal_user = uuid.uuid4()
    now = datetime.now(timezone.utc)

    for _ in range(5):  # exactly at threshold, not over it
        await _add_priority_change(db, token.id, normal_user, now)
    await db.flush()

    alerts = await service.get_priority_elevation_alerts(db, department_id, date.today(), facility_id)
    assert alerts == []


async def test_scoped_to_department(db):
    facility_id, dept_a = await _make_facility_and_department(db)
    _facility_id_b, dept_b = await _make_facility_and_department(db)
    token_a = await _make_queue_and_token(db, facility_id, dept_a)
    token_b = await _make_queue_and_token(db, facility_id, dept_b)
    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    for _ in range(6):
        await _add_priority_change(db, token_a.id, user_id, now)
    for _ in range(6):
        await _add_priority_change(db, token_b.id, user_id, now)
    await db.flush()

    alerts = await service.get_priority_elevation_alerts(db, dept_a, date.today(), facility_id)
    assert len(alerts) == 1  # only dept_a's 6 count, not dept_b's separate 6

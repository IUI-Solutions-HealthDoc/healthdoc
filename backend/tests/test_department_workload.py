"""Tests for task 8's department workload summary (HOD dashboard).
Tested directly against the service layer, no HTTP/JWT needed.
"""
import uuid
from datetime import date

import pytest

from app.common.enums import QueuePriority, QueueTokenStatus
from app.departments.models import Department
from app.queue import service
from app.queue.models import Queue, QueueToken
from app.users.models import Facility

pytestmark = pytest.mark.asyncio


async def _make_facility_and_department(db):
    facility_id = uuid.uuid4()
    department_id = uuid.uuid4()
    db.add(Facility(id=facility_id, code=f"F{uuid.uuid4().hex[:4]}", name="Test Facility", state_code="TS"))
    db.add(Department(id=department_id, code=f"D{uuid.uuid4().hex[:4]}", name="Test Dept", facility_id=facility_id))
    await db.flush()
    return facility_id, department_id


async def _make_token(db, queue_id, facility_id, status, sequence=1):
    token = QueueToken(
        id=uuid.uuid4(), facility_id=facility_id, queue_id=queue_id,
        visit_id=uuid.uuid4(), sequence=sequence, token_display=f"MED-{sequence:03d}",
        initial_priority=QueuePriority.NORMAL.value, status=status,
        priority=QueuePriority.NORMAL.value, priority_rank=6,
    )
    db.add(token)


async def test_workload_counts_waiting_open_closed_completed(db):
    facility_id, department_id = await _make_facility_and_department(db)
    today = date.today()

    open_queue = Queue(
        id=uuid.uuid4(), facility_id=facility_id, department_id=department_id,
        doctor_user_id=uuid.uuid4(), service_date=today, is_open=True,
    )
    closed_queue = Queue(
        id=uuid.uuid4(), facility_id=facility_id, department_id=department_id,
        doctor_user_id=uuid.uuid4(), service_date=today, is_open=False,
    )
    db.add_all([open_queue, closed_queue])
    await db.flush()

    await _make_token(db, open_queue.id, facility_id, QueueTokenStatus.WAITING.value, sequence=1)
    await _make_token(db, open_queue.id, facility_id, QueueTokenStatus.WAITING.value, sequence=2)
    await _make_token(db, closed_queue.id, facility_id, QueueTokenStatus.COMPLETED.value, sequence=1)
    await db.flush()

    workload = await service.get_department_workload(db, department_id, today, facility_id)

    assert workload["total_waiting"] == 2
    assert workload["queues_open"] == 1
    assert workload["queues_closed"] == 1
    assert workload["completed_today"] == 1


async def test_workload_zero_when_no_queues(db):
    facility_id, department_id = await _make_facility_and_department(db)
    workload = await service.get_department_workload(db, department_id, date.today(), facility_id)

    assert workload["total_waiting"] == 0
    assert workload["queues_open"] == 0
    assert workload["queues_closed"] == 0
    assert workload["completed_today"] == 0


async def test_workload_rejects_wrong_facility(db):
    facility_id, department_id = await _make_facility_and_department(db)
    other_facility_id = uuid.uuid4()

    with pytest.raises(Exception) as exc_info:
        await service.get_department_workload(db, department_id, date.today(), other_facility_id)
    assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()

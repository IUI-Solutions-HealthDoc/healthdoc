"""Tests for task 8's token reassignment (HOD dashboard). Tested
directly against the service layer, no HTTP/JWT needed.
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


async def _make_queue(db, facility_id, department_id, doctor_id=None):
    queue = Queue(
        id=uuid.uuid4(), facility_id=facility_id, department_id=department_id,
        doctor_user_id=doctor_id or uuid.uuid4(), service_date=date.today(), is_open=True,
    )
    db.add(queue)
    await db.flush()
    return queue


async def test_reassign_moves_waiting_token_to_new_queue(db):
    facility_id, department_id = await _make_facility_and_department(db)
    source_queue = await _make_queue(db, facility_id, department_id)
    target_queue = await _make_queue(db, facility_id, department_id)

    old_token = QueueToken(
        id=uuid.uuid4(), facility_id=facility_id, queue_id=source_queue.id,
        visit_id=uuid.uuid4(), sequence=1, token_display="MED-001",
        initial_priority=QueuePriority.NORMAL.value, status=QueueTokenStatus.WAITING.value,
        priority=QueuePriority.EMERGENCY.value, priority_rank=0,
    )
    db.add(old_token)
    await db.flush()

    new_token = await service.reassign_token(
        db, old_token.id, target_queue.id,
        caller_facility_id=facility_id, caller_roles=["admin"], caller_department_id=None,
    )

    assert new_token.queue_id == target_queue.id
    assert new_token.token_display == "MED-001"
    assert new_token.priority == QueuePriority.EMERGENCY.value  # carried over
    assert new_token.status == QueueTokenStatus.WAITING.value

    await db.refresh(old_token)
    assert old_token.status == QueueTokenStatus.TRANSFERRED.value


async def test_reassign_rejects_non_waiting_token(db):
    facility_id, department_id = await _make_facility_and_department(db)
    source_queue = await _make_queue(db, facility_id, department_id)
    target_queue = await _make_queue(db, facility_id, department_id)

    called_token = QueueToken(
        id=uuid.uuid4(), facility_id=facility_id, queue_id=source_queue.id,
        visit_id=uuid.uuid4(), sequence=1, token_display="MED-001",
        initial_priority=QueuePriority.NORMAL.value, status=QueueTokenStatus.CALLED.value,
        priority=QueuePriority.NORMAL.value, priority_rank=6,
    )
    db.add(called_token)
    await db.flush()

    with pytest.raises(Exception) as exc_info:
        await service.reassign_token(
            db, called_token.id, target_queue.id,
            caller_facility_id=facility_id, caller_roles=["admin"], caller_department_id=None,
        )
    assert "409" in str(exc_info.value) or "Cannot reassign" in str(exc_info.value)


async def test_reassign_rejects_different_department(db):
    facility_id, dept_a = await _make_facility_and_department(db)
    _facility_id_b, dept_b = await _make_facility_and_department(db)
    source_queue = await _make_queue(db, facility_id, dept_a)
    target_queue = await _make_queue(db, facility_id, dept_b)

    token = QueueToken(
        id=uuid.uuid4(), facility_id=facility_id, queue_id=source_queue.id,
        visit_id=uuid.uuid4(), sequence=1, token_display="MED-001",
        initial_priority=QueuePriority.NORMAL.value, status=QueueTokenStatus.WAITING.value,
        priority=QueuePriority.NORMAL.value, priority_rank=6,
    )
    db.add(token)
    await db.flush()

    with pytest.raises(Exception) as exc_info:
        await service.reassign_token(
            db, token.id, target_queue.id,
            caller_facility_id=facility_id, caller_roles=["admin"], caller_department_id=None,
        )
    assert "same department" in str(exc_info.value)


async def test_reassign_rejects_doctor_role(db):
    facility_id, department_id = await _make_facility_and_department(db)
    source_queue = await _make_queue(db, facility_id, department_id)
    target_queue = await _make_queue(db, facility_id, department_id)

    token = QueueToken(
        id=uuid.uuid4(), facility_id=facility_id, queue_id=source_queue.id,
        visit_id=uuid.uuid4(), sequence=1, token_display="MED-001",
        initial_priority=QueuePriority.NORMAL.value, status=QueueTokenStatus.WAITING.value,
        priority=QueuePriority.NORMAL.value, priority_rank=6,
    )
    db.add(token)
    await db.flush()

    with pytest.raises(Exception) as exc_info:
        await service.reassign_token(
            db, token.id, target_queue.id,
            caller_facility_id=facility_id, caller_roles=["doctor"], caller_department_id=None,
        )
    assert "Only hod or admin" in str(exc_info.value)
    
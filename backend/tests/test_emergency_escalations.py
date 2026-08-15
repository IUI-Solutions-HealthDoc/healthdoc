"""Tests for task 8's emergency escalations (HOD dashboard). Tested
directly against the service layer, no HTTP/JWT needed.
"""
import uuid
from datetime import date

import pytest

from app.common.enums import QueuePriority, QueueTokenStatus
from app.departments.models import Department
from app.queue import service
from app.queue.models import Queue, QueueToken
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def _make_facility_and_department(db):
    facility_id = uuid.uuid4()
    department_id = uuid.uuid4()
    db.add(Facility(id=facility_id, code=f"F{uuid.uuid4().hex[:4]}", name="Test Facility", state_code="TS"))
    db.add(Department(id=department_id, code=f"D{uuid.uuid4().hex[:4]}", name="Test Dept", facility_id=facility_id))
    await db.flush()
    return facility_id, department_id


async def _make_queue(db, facility_id, department_id):
    doctor_id = uuid.uuid4()
    db.add(User(
        id=doctor_id, keycloak_sub=f"sub-{uuid.uuid4()}", username=f"u{uuid.uuid4().hex[:6]}",
        full_name="Dr. Emergency", facility_id=facility_id,
    ))
    queue = Queue(
        id=uuid.uuid4(), facility_id=facility_id, department_id=department_id,
        doctor_user_id=doctor_id, service_date=date.today(), is_open=True,
    )
    db.add(queue)
    await db.flush()
    return queue


async def test_surfaces_active_emergency_tokens(db):
    facility_id, department_id = await _make_facility_and_department(db)
    queue = await _make_queue(db, facility_id, department_id)

    emergency_token = QueueToken(
        id=uuid.uuid4(), facility_id=facility_id, queue_id=queue.id,
        visit_id=uuid.uuid4(), sequence=1, token_display="MED-001",
        initial_priority=QueuePriority.EMERGENCY.value, status=QueueTokenStatus.WAITING.value,
        priority=QueuePriority.EMERGENCY.value, priority_rank=0,
    )
    normal_token = QueueToken(
        id=uuid.uuid4(), facility_id=facility_id, queue_id=queue.id,
        visit_id=uuid.uuid4(), sequence=2, token_display="MED-002",
        initial_priority=QueuePriority.NORMAL.value, status=QueueTokenStatus.WAITING.value,
        priority=QueuePriority.NORMAL.value, priority_rank=6,
    )
    db.add_all([emergency_token, normal_token])
    await db.flush()

    escalations = await service.get_emergency_escalations(db, department_id, facility_id)

    assert len(escalations) == 1
    assert escalations[0]["token_display"] == "MED-001"
    assert escalations[0]["doctor_name"] == "Dr. Emergency"


async def test_excludes_completed_emergency_tokens(db):
    facility_id, department_id = await _make_facility_and_department(db)
    queue = await _make_queue(db, facility_id, department_id)

    resolved_token = QueueToken(
        id=uuid.uuid4(), facility_id=facility_id, queue_id=queue.id,
        visit_id=uuid.uuid4(), sequence=1, token_display="MED-001",
        initial_priority=QueuePriority.EMERGENCY.value, status=QueueTokenStatus.COMPLETED.value,
        priority=QueuePriority.EMERGENCY.value, priority_rank=0,
    )
    db.add(resolved_token)
    await db.flush()

    escalations = await service.get_emergency_escalations(db, department_id, facility_id)
    assert escalations == []


async def test_empty_when_no_queues(db):
    facility_id, department_id = await _make_facility_and_department(db)
    escalations = await service.get_emergency_escalations(db, department_id, facility_id)
    assert escalations == []


async def test_rejects_wrong_facility(db):
    facility_id, department_id = await _make_facility_and_department(db)
    other_facility_id = uuid.uuid4()

    with pytest.raises(Exception) as exc_info:
        await service.get_emergency_escalations(db, department_id, other_facility_id)
    assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()

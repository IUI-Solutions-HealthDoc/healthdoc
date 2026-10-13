"""Cover for an absent doctor: hand a whole queue to a colleague.

Every waiting patient moves in the order they would have been seen, nobody
already called is moved, the source queue closes, and a repeat is harmless.
"""
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.common.enums import QueuePriority, QueueTokenStatus
from app.queue import service
from app.queue.models import QueueToken
from tests.test_reassign_token import _make_facility_and_department, _make_queue

pytestmark = pytest.mark.asyncio


async def _token(db, facility_id, queue, seq, *, status=QueueTokenStatus.WAITING.value, rank=6):
    token = QueueToken(
        id=uuid.uuid4(), facility_id=facility_id, queue_id=queue.id, visit_id=uuid.uuid4(), sequence=seq,
        token_display=f"MED-{seq:03d}", initial_priority=QueuePriority.NORMAL.value, status=status,
        priority=QueuePriority.NORMAL.value, priority_rank=rank,
    )
    db.add(token)
    await db.flush()
    return token


async def test_waiting_patients_move_in_turn_and_the_queue_closes(db):
    facility_id, department_id = await _make_facility_and_department(db)
    absent = await _make_queue(db, facility_id, department_id)
    cover = await _make_queue(db, facility_id, department_id)
    await _token(db, facility_id, cover, 1)
    await _token(db, facility_id, absent, 1)
    await _token(db, facility_id, absent, 2, rank=0)                                  # urgent: goes first
    await _token(db, facility_id, absent, 3, status=QueueTokenStatus.CALLED.value)   # already with someone

    moved = await service.hand_over_queue(
        db, absent.id, cover.id, caller_facility_id=facility_id, caller_roles=["admin"], caller_department_id=None,
    )
    assert moved == 2
    arrived = (
        await db.execute(
            select(QueueToken.token_display)
            .where(QueueToken.queue_id == cover.id, QueueToken.status == QueueTokenStatus.WAITING.value)
            .order_by(QueueToken.sequence)
        )
    ).scalars().all()
    assert arrived == ["MED-001", "MED-002", "MED-001"]
    await db.refresh(absent)
    assert absent.is_open is False

    again = await service.hand_over_queue(
        db, absent.id, cover.id, caller_facility_id=facility_id, caller_roles=["admin"], caller_department_id=None,
    )
    assert again == 0


async def test_an_hod_cannot_hand_over_another_departments_queue(db):
    facility_id, department_id = await _make_facility_and_department(db)
    absent = await _make_queue(db, facility_id, department_id)
    cover = await _make_queue(db, facility_id, department_id)
    await _token(db, facility_id, absent, 1)
    with pytest.raises(HTTPException) as refused:
        await service.hand_over_queue(
            db, absent.id, cover.id, caller_facility_id=facility_id, caller_roles=["hod"],
            caller_department_id=uuid.uuid4(),
        )
    assert refused.value.status_code == 403


async def test_an_empty_queue_still_checks_the_department(db):
    facility_id, dept_a = await _make_facility_and_department(db)
    other_department = (await _make_facility_and_department(db))[1]
    absent = await _make_queue(db, facility_id, dept_a)
    elsewhere = await _make_queue(db, facility_id, other_department)
    with pytest.raises(HTTPException) as refused:
        await service.hand_over_queue(
            db, absent.id, elsewhere.id, caller_facility_id=facility_id, caller_roles=["admin"],
            caller_department_id=None,
        )
    assert refused.value.status_code == 422


async def test_another_facilitys_queue_is_not_found(db):
    facility_id, department_id = await _make_facility_and_department(db)
    other_facility, other_department = await _make_facility_and_department(db)
    absent = await _make_queue(db, facility_id, department_id)
    theirs = await _make_queue(db, other_facility, other_department)
    await _token(db, facility_id, absent, 1)
    with pytest.raises(HTTPException) as refused:
        await service.hand_over_queue(
            db, absent.id, theirs.id, caller_facility_id=facility_id, caller_roles=["admin"], caller_department_id=None,
        )
    assert refused.value.status_code == 404

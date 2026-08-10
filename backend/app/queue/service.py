"""Queue operations — create queue, token generation, automatic call-next,
priority elevation, listing.

Call-next is automatic: a prescription/order created for a visit is the
"consultation over" signal; complete_by_visit_id() is the trigger point.
Admin has manual overrides for edge cases only.
"""
import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.common.business_date import get_business_date
from app.common.enums import QueuePriority, QueueTokenStatus
from app.common.redis import queue_channel
from app.departments.models import Department, Room
from app.notifications.models import NotificationHistory
from app.queue.models import Queue, QueueCounter, QueueToken, QueueTokenPriorityChange
from app.users.models import User

PRIORITY_RANK = {
    QueuePriority.EMERGENCY.value: 0,
    QueuePriority.DOCTOR_RECALL.value: 1,
    QueuePriority.ADMIN_OVERRIDE.value: 2,
    QueuePriority.SENIOR_CITIZEN.value: 3,
    QueuePriority.PREGNANT.value: 4,
    QueuePriority.FOLLOW_UP_RECALL.value: 5,
    QueuePriority.NORMAL.value: 6,
}

TIER_ALLOWED_ROLES: dict[str, set[str]] = {
    QueuePriority.SENIOR_CITIZEN.value: {"receptionist"},
    QueuePriority.PREGNANT.value: {"receptionist"},
    QueuePriority.FOLLOW_UP_RECALL.value: {"receptionist", "doctor"},
    QueuePriority.DOCTOR_RECALL.value: {"doctor"},
    QueuePriority.EMERGENCY.value: {"emergency", "doctor", "hod"},
    QueuePriority.ADMIN_OVERRIDE.value: {"hod"},
}

CALLABLE_STATUSES = (QueueTokenStatus.WAITING.value, QueueTokenStatus.RECALLED.value)

_NOT_FOUND = HTTPException(404, "Queue not found")


# ---------------- CALLER CONTEXT RESOLUTION ----------------
# resolve_caller_facility_id() lived here and did exactly what CurrentDbUser
# now does — one extra users lookup per request to get facility_id from a
# keycloak_sub. The routers take CurrentDbUser directly instead.
#
# resolve_caller_full_context stays only because DbUser doesn't carry
# department_id. Add it there and this can go too.
async def resolve_caller_full_context(
    db: AsyncSession, keycloak_sub: str
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]:
    row = await db.execute(
        select(User.id, User.facility_id, User.department_id).where(User.keycloak_sub == keycloak_sub)
    )
    result = row.one_or_none()
    if result is None:
        raise HTTPException(403, "No matching user profile for this account")
    return result[0], result[1], result[2]


# ---------------- FACILITY-SCOPED FETCH ----------------
async def _get_scoped_queue(
    db: AsyncSession, queue_id: uuid.UUID, caller_facility_id: uuid.UUID, for_update: bool = False
) -> Queue:
    q = select(Queue).where(Queue.id == queue_id)
    if for_update:
        q = q.with_for_update()
    queue = (await db.execute(q)).scalar_one_or_none()
    if queue is None or queue.facility_id != caller_facility_id:
        raise _NOT_FOUND
    return queue

async def _get_scoped_token(
    db: AsyncSession, token_id: uuid.UUID, caller_facility_id: uuid.UUID, for_update: bool = False
) -> tuple[QueueToken, Queue]:
    q = select(QueueToken).where(QueueToken.id == token_id)
    if for_update:
        q = q.with_for_update()
    token = (await db.execute(q)).scalar_one_or_none()
    if token is None:
        raise HTTPException(404, "Token not found")
 
    queue = (
        await db.execute(select(Queue).where(Queue.id == token.queue_id).with_for_update())
    ).scalar_one_or_none()
    if queue is None or queue.facility_id != caller_facility_id:
        raise HTTPException(404, "Token not found")
    return token, queue


# ---------------- CREATE QUEUE ----------------
async def create_queue(
    db: AsyncSession,
    department_id: uuid.UUID,
    doctor_user_id: uuid.UUID,
    room_id: uuid.UUID | None,
    display_label: str | None,
    service_date: date,
    caller_facility_id: uuid.UUID,
) -> Queue:
    department = await db.get(Department, department_id)
    if department is None:
        raise HTTPException(404, "Department not found")
    if department.facility_id != caller_facility_id:
        raise HTTPException(404, "Department not found")
    
    existing = (
        await db.execute(
            select(Queue).where(
                Queue.department_id == department_id,
                Queue.doctor_user_id == doctor_user_id,
                Queue.service_date == service_date,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, "Queue already exists for this doctor/department/date")

    queue = Queue(
        id=uuid.uuid4(),
        facility_id=department.facility_id,
        department_id=department_id,
        doctor_user_id=doctor_user_id,
        room_id=room_id,
        display_label=display_label,
        service_date=service_date,
    )
    db.add(queue)
    await db.flush()
    await db.refresh(queue)
    return queue


async def _allocate_token_number(db: AsyncSession, department_id: uuid.UUID, business_date: date) -> int:
    counter = (
        await db.execute(
            select(QueueCounter)
            .where(QueueCounter.department_id == department_id, QueueCounter.counter_date == business_date)
            .with_for_update()
        )
    ).scalar_one_or_none()
 
    if counter is None:
        counter = QueueCounter(
            id=uuid.uuid4(), department_id=department_id, counter_date=business_date, last_value=0
        )
        db.add(counter)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            counter = (
                await db.execute(
                    select(QueueCounter)
                    .where(QueueCounter.department_id == department_id, QueueCounter.counter_date == business_date)
                    .with_for_update()
                )
            ).scalar_one()
 
    counter.last_value += 1
    await db.flush()
    return counter.last_value


# ---------------- CREATE TOKEN ----------------
async def create_token(
    db: AsyncSession,
    queue_id: uuid.UUID,
    visit_id: uuid.UUID,
    priority: str,
    caller_facility_id: uuid.UUID,
) -> QueueToken:
    if visit_id is None:
        raise HTTPException(422, "visit_id is required to create a queue token")

    queue = await _get_scoped_queue(db, queue_id, caller_facility_id, for_update=True)
    if not queue.is_open:
        raise HTTPException(409, "Queue is closed")
    if priority not in PRIORITY_RANK:
        raise HTTPException(422, f"Invalid priority '{priority}'")

    department = await db.get(Department, queue.department_id)
    if department is None:
        raise HTTPException(404, "Department not found")

    # MAX(sequence)+1 is safe HERE, and only here, because _get_scoped_queue
    # above took the parent `queues` row with FOR UPDATE. Two concurrent
    # create_token calls for the same queue serialise on that lock, so the
    # second reads MAX only after the first has committed its token — and
    # `sequence` is unique per queue_id, which is exactly the granularity the
    # queue-row lock gives us.
    #
    # Do NOT copy this pattern anywhere the parent row isn't already locked.
    # The display counter below is the general case: queue_counters exists
    # because token_display is per (department, day) and no single row lock
    # covers it.
    next_seq_expr = func.coalesce(func.max(QueueToken.sequence), 0) + 1  # pr-check: ignore
    next_seq = (
        await db.execute(select(next_seq_expr).where(QueueToken.queue_id == queue_id))
    ).scalar_one()

    business_date = await get_business_date(db, queue.facility_id)
    token_number = await _allocate_token_number(db, queue.department_id, business_date)

    token = QueueToken(
        id=uuid.uuid4(),
        facility_id=queue.facility_id,
        queue_id=queue_id,
        visit_id=visit_id,
        sequence=next_seq,
        token_display=f"{department.code}-{token_number:03d}",
        initial_priority=priority,
        status=QueueTokenStatus.WAITING.value,
        priority=priority,
        priority_rank=PRIORITY_RANK[priority],
    )
    db.add(token)
    await db.flush()
    await db.refresh(token)
    return token


# ---------------- STUCK-TOKEN SAFETY NET ----------------
async def _find_unresolved_called_token(db: AsyncSession, queue_id: uuid.UUID) -> QueueToken | None:
    return (
        await db.execute(
            select(QueueToken).where(
                QueueToken.queue_id == queue_id,
                QueueToken.status == QueueTokenStatus.CALLED.value,
            ).limit(1)
        )
    ).scalar_one_or_none()


# ---------------- ADVANCE QUEUE (shared by manual + automatic paths) ----------------
async def _advance_queue(db: AsyncSession, queue: Queue) -> tuple[QueueToken | None, dict | None]:
    # Assumes `queue` is already locked by the caller. Returns None if
    # closed/empty/stuck -- can run inside another module's transaction
    # and must never raise there."""
    if not queue.is_open:
        return None, None
    if await _find_unresolved_called_token(db, queue.id) is not None:
        return None, None

    candidates = (
        (
            await db.execute(
                select(QueueToken).where(
                    QueueToken.queue_id == queue.id,
                    QueueToken.status.in_(CALLABLE_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    if not candidates:
        return None, None

    candidates.sort(key=lambda t: (t.priority_rank, t.created_at, t.sequence))
    next_token = candidates[0]

    next_token.status = QueueTokenStatus.CALLED.value
    next_token.called_at = datetime.now(timezone.utc)
    queue.now_serving_token_id = next_token.id

    await db.flush()
    await db.refresh(next_token)

    doctor = await db.get(User, queue.doctor_user_id)
    room = await db.get(Room, queue.room_id) if queue.room_id else None

    payload = {
        "department_id": str(queue.department_id),
        "queue_id": str(queue.id),
        "doctor_name": doctor.full_name if doctor else None,
        "room_number": room.room_number if room else None,
        "token_display": next_token.token_display,
        "now_serving": next_token.token_display,
    }

    db.add(NotificationHistory(
        id=uuid.uuid4(),
        event_type="token_called",
        payload=payload,
        department_id=queue.department_id,
    ))
    await db.flush()

    pending_event = {
        "channel": queue_channel(queue.department_id),
        "event_type": "token_called",
        "payload": payload,
    }
    return next_token, pending_event


# ---------------- ADMIN MANUAL OVERRIDE: CALL NEXT ----------------
async def call_next_token(
    db: AsyncSession,
    queue_id: uuid.UUID,
    caller_facility_id: uuid.UUID,
) -> tuple[QueueToken, dict | None]:
    queue = await _get_scoped_queue(db, queue_id, caller_facility_id, for_update=True)
    if not queue.is_open:
        raise HTTPException(409, "Queue is closed")

    stuck = await _find_unresolved_called_token(db, queue_id)
    if stuck is not None:
        raise HTTPException(
            409,
            f"Token {stuck.token_display} is still 'called' and unresolved — "
            f"resolve it first (e.g. admin_force_complete) before calling the next one",
        )

    next_token, pending_event = await _advance_queue(db, queue)
    if next_token is None:
        raise HTTPException(404, "No waiting tokens in this queue")
    return next_token, pending_event


# ---------------- COMPLETE + ADVANCE (automatic trigger core) ----------------
async def _complete_token_and_advance(
    db: AsyncSession, token: QueueToken
) -> tuple[QueueToken, QueueToken | None, dict | None]:
    if token.status != QueueTokenStatus.CALLED.value:
        raise HTTPException(409, f"Token must be 'called' to complete it (currently '{token.status}')")

    queue = (
        await db.execute(select(Queue).where(Queue.id == token.queue_id).with_for_update())
    ).scalar_one_or_none()
    if queue is None:
        raise HTTPException(404, "Queue not found")

    token.status = QueueTokenStatus.COMPLETED.value
    token.completed_at = datetime.now(timezone.utc)
    if queue.now_serving_token_id == token.id:
        queue.now_serving_token_id = None

    await db.flush()
    await db.refresh(token)

    next_token, pending_event = await _advance_queue(db, queue)
    return token, next_token, pending_event


async def complete_by_visit_id(
    db: AsyncSession, visit_id: uuid.UUID
) -> tuple[QueueToken, QueueToken | None, dict | None]:
    # Call from prescriptions/orders, same DB transaction, right after
    # creating the prescription/order:
    # await complete_by_visit_id(db, prescription.visit_id)
    token = (
        await db.execute(
            select(QueueToken)
            .where(
                QueueToken.visit_id == visit_id,
                QueueToken.status == QueueTokenStatus.CALLED.value,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if token is None:
        raise HTTPException(404, "No currently-called queue token found for this visit")

    return await _complete_token_and_advance(db, token)


async def admin_force_complete(
    db: AsyncSession,
    token_id: uuid.UUID,
    caller_facility_id: uuid.UUID,
) -> tuple[QueueToken, QueueToken | None, dict | None]:
    token, _queue = await _get_scoped_token(db, token_id, caller_facility_id, for_update=True)
    return await _complete_token_and_advance(db, token)


# ---------------- PRIORITY ELEVATION ----------------
async def elevate_priority(
    db: AsyncSession,
    token_id: uuid.UUID,
    new_priority: str,
    reason: str,
    caller_sub: str,
    caller_roles: list[str],
    caller_amr: list[str],
    caller_facility_id: uuid.UUID,
) -> QueueToken:
    if new_priority not in PRIORITY_RANK:
        raise HTTPException(422, f"Invalid priority '{new_priority}'")
    if reason is None or len(reason.strip()) < 10:
        raise HTTPException(422, "reason must be at least 10 characters")
 
    token, queue = await _get_scoped_token(db, token_id, caller_facility_id, for_update=True)
 
    if token.status != QueueTokenStatus.WAITING.value:
        raise HTTPException(409, f"Cannot change priority on a token with status '{token.status}'")
 
    old_priority = token.priority
    old_rank = PRIORITY_RANK[old_priority]
    new_rank = PRIORITY_RANK[new_priority]
 
    if new_rank == old_rank:
        raise HTTPException(422, f"Token is already '{old_priority}'")
 
    caller_user_id, _caller_facility_id, caller_department_id = await resolve_caller_full_context(
        db, caller_sub
    )
 
    if new_rank < old_rank:
        # Elevating -- role must be allowed for the target tier.
        allowed_roles = TIER_ALLOWED_ROLES.get(new_priority, set())
        if not allowed_roles & set(caller_roles):
            raise HTTPException(403, f"Your role cannot set priority to '{new_priority}'")
 
        if new_priority == QueuePriority.DOCTOR_RECALL.value:
            if queue.doctor_user_id != caller_user_id:
                raise HTTPException(403, "doctor_recall may only be set by this queue's own doctor")
 
        if new_priority == QueuePriority.ADMIN_OVERRIDE.value:
            if "hod" not in caller_roles:
                raise HTTPException(403, "admin_override may only be set by hod")
            if caller_department_id != queue.department_id:
                raise HTTPException(403, "hod may only act within their own department")
            if "otp" not in caller_amr:
                raise HTTPException(403, "admin_override requires an active MFA session")
    else:
        # Demoting -- only hod, regardless of target tier.
        if "hod" not in caller_roles:
            raise HTTPException(403, "Only hod may lower a token's priority")
        if caller_department_id != queue.department_id:
            raise HTTPException(403, "hod may only act within their own department")
 
    db.add(QueueTokenPriorityChange(
        id=uuid.uuid4(),
        queue_token_id=token.id,
        from_priority=old_priority,
        to_priority=new_priority,
        reason=reason.strip(),
        changed_by=caller_user_id,
    ))
 
    token.priority = new_priority
    token.priority_rank = new_rank
    await db.flush()
    await db.refresh(token)
    return token


# ---------------- LIST QUEUE TOKENS ----------------
async def list_queue_tokens(
    db: AsyncSession,
    queue_id: uuid.UUID,
    caller_facility_id: uuid.UUID,
) -> dict:
    queue = await _get_scoped_queue(db, queue_id, caller_facility_id)

    doctor = await db.get(User, queue.doctor_user_id)
    room = await db.get(Room, queue.room_id) if queue.room_id else None
    doctor_name = doctor.full_name if doctor else None
    room_number = room.room_number if room else None

    tokens = (
        (
            await db.execute(
                select(QueueToken).where(
                    QueueToken.queue_id == queue_id,
                    QueueToken.status != QueueTokenStatus.CANCELLED.value,
                )
            )
        )
        .scalars()
        .all()
    )
    tokens.sort(key=lambda t: (t.priority_rank, t.created_at, t.sequence))
    
    waiting_count = sum(1 for t in tokens if t.status in CALLABLE_STATUSES)

    now_serving = None
    if queue.now_serving_token_id:
        now_serving_token = next((t for t in tokens if t.id == queue.now_serving_token_id), None)
        if now_serving_token:
            now_serving = now_serving_token.token_display

    items = [
        {
            "id": t.id,
            "queue_id": t.queue_id,
            "visit_id": t.visit_id,
            "sequence": t.sequence,
            "token_display": t.token_display,
            "status": t.status,
            "priority": t.priority,
            "created_at": t.created_at,
            "called_at": t.called_at,
            "completed_at": t.completed_at,
            "doctor_name": doctor_name,
            "room_number": room_number,
        }
        for t in tokens
    ]

    return {"waiting_count": waiting_count, "now_serving": now_serving, "items": items}

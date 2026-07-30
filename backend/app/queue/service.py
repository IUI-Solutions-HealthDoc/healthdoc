"""Queue operations — create queue, token generation, automatic call-next,
priority elevation, listing.

Call-next is automatic: when a prescription/order is created for a visit,
that's the "consultation over" signal. complete_by_visit_id() is the trigger
point other modules call once they exist. Admin has manual overrides for
edge cases; no other role can call-next or force-complete.
"""
import uuid
from datetime import date

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import QueuePriority, QueueTokenStatus
from app.common.redis import publish_event, queue_channel
from app.departments.models import Department, Room
from app.notifications.models import NotificationHistory
from app.queue.models import Queue, QueueToken
from app.users.models import User

PRIORITY_ORDER = {
    QueuePriority.EMERGENCY.value: 0,
    QueuePriority.DOCTOR_RECALL.value: 1,
    QueuePriority.ADMIN_OVERRIDE.value: 2,
    QueuePriority.SENIOR_CITIZEN.value: 3,
    QueuePriority.PREGNANT.value: 4,
    QueuePriority.FOLLOW_UP_RECALL.value: 5,
    QueuePriority.NORMAL.value: 6,
}

CALLABLE_STATUSES = (QueueTokenStatus.WAITING.value, QueueTokenStatus.RECALLED.value)


# ---------------- CREATE QUEUE ----------------
async def create_queue(
    db: AsyncSession,
    department_id: uuid.UUID,
    doctor_user_id: uuid.UUID,
    room_id: uuid.UUID | None,
    display_label: str | None,
    service_date: date,
) -> Queue:
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


# ---------------- CREATE TOKEN ----------------
async def create_token(
    db: AsyncSession,
    queue_id: uuid.UUID,
    visit_id: uuid.UUID,
    priority: str,
) -> QueueToken:
    if visit_id is None:
        raise HTTPException(422, "visit_id is required to create a queue token")

    queue = (
        await db.execute(select(Queue).where(Queue.id == queue_id).with_for_update())
    ).scalar_one_or_none()
    if queue is None:
        raise HTTPException(404, "Queue not found")
    if not queue.is_open:
        raise HTTPException(409, "Queue is closed")
    if priority not in PRIORITY_ORDER:
        raise HTTPException(422, f"Invalid priority '{priority}'")

    department = await db.get(Department, queue.department_id)
    if department is None:
        raise HTTPException(404, "Department not found")

    next_seq = (
        await db.execute(
            select(func.coalesce(func.max(QueueToken.sequence), 0) + 1).where(
                QueueToken.queue_id == queue_id
            )
        )
    ).scalar_one()

    token = QueueToken(
        id=uuid.uuid4(),
        queue_id=queue_id,
        visit_id=visit_id,
        sequence=next_seq,
        token_display=f"{department.code}-{next_seq:03d}",
        status=QueueTokenStatus.WAITING.value,
        priority=priority,
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
            )
        )
    ).scalar_one_or_none()


# ---------------- ADVANCE QUEUE (shared by manual + automatic paths) ----------------
async def _advance_queue(db: AsyncSession, queue: Queue) -> QueueToken | None:
    """Assumes `queue` is already locked by the caller. Returns None (no
    exception) if closed, empty, or a stuck token exists — this can run
    inside another module's transaction and must never raise there."""
    if not queue.is_open:
        return None
    if await _find_unresolved_called_token(db, queue.id) is not None:
        return None

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
        return None

    candidates.sort(key=lambda t: (PRIORITY_ORDER.get(t.priority, 99), t.created_at, t.sequence))
    next_token = candidates[0]

    next_token.status = QueueTokenStatus.CALLED.value
    next_token.called_at = func.now()
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

    await publish_event(queue_channel(queue.department_id), "token_called", payload)
    return next_token


# ---------------- ADMIN MANUAL OVERRIDE: CALL NEXT ----------------
async def call_next_token(db: AsyncSession, queue_id: uuid.UUID) -> QueueToken:
    queue = (
        await db.execute(select(Queue).where(Queue.id == queue_id).with_for_update())
    ).scalar_one_or_none()
    if queue is None:
        raise HTTPException(404, "Queue not found")
    if not queue.is_open:
        raise HTTPException(409, "Queue is closed")

    stuck = await _find_unresolved_called_token(db, queue_id)
    if stuck is not None:
        raise HTTPException(
            409,
            f"Token {stuck.token_display} is still 'called' and unresolved — "
            f"resolve it first (e.g. admin_force_complete) before calling the next one",
        )

    next_token = await _advance_queue(db, queue)
    if next_token is None:
        raise HTTPException(404, "No waiting tokens in this queue")
    return next_token


# ---------------- COMPLETE + ADVANCE (automatic trigger core) ----------------
async def _complete_token_and_advance(
    db: AsyncSession, token: QueueToken
) -> tuple[QueueToken, QueueToken | None]:
    if token.status != QueueTokenStatus.CALLED.value:
        raise HTTPException(409, f"Token must be 'called' to complete it (currently '{token.status}')")

    queue = (
        await db.execute(select(Queue).where(Queue.id == token.queue_id).with_for_update())
    ).scalar_one_or_none()
    if queue is None:
        raise HTTPException(404, "Queue not found")

    token.status = QueueTokenStatus.COMPLETED.value
    token.completed_at = func.now()
    if queue.now_serving_token_id == token.id:
        queue.now_serving_token_id = None

    await db.flush()
    await db.refresh(token)

    next_token = await _advance_queue(db, queue)
    return token, next_token


async def complete_by_visit_id(
    db: AsyncSession, visit_id: uuid.UUID
) -> tuple[QueueToken, QueueToken | None]:
    """Call from the prescriptions/orders module, same DB transaction, right
    after creating the prescription/order:
        await complete_by_visit_id(db, prescription.visit_id)
    """
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
    db: AsyncSession, token_id: uuid.UUID
) -> tuple[QueueToken, QueueToken | None]:
    token = (
        await db.execute(select(QueueToken).where(QueueToken.id == token_id).with_for_update())
    ).scalar_one_or_none()
    if token is None:
        raise HTTPException(404, "Token not found")
    return await _complete_token_and_advance(db, token)


# ---------------- PRIORITY ELEVATION ----------------
async def elevate_priority(db: AsyncSession, token_id: uuid.UUID, new_priority: str) -> QueueToken:
    if new_priority not in PRIORITY_ORDER:
        raise HTTPException(422, f"Invalid priority '{new_priority}'")

    token = await db.get(QueueToken, token_id)
    if token is None:
        raise HTTPException(404, "Token not found")
    if token.status not in CALLABLE_STATUSES:
        raise HTTPException(409, f"Cannot change priority on a token with status '{token.status}'")

    token.priority = new_priority
    await db.flush()
    await db.refresh(token)
    return token


# ---------------- LIST QUEUE TOKENS ----------------
async def list_queue_tokens(db: AsyncSession, queue_id: uuid.UUID) -> dict:
    queue = (await db.execute(select(Queue).where(Queue.id == queue_id))).scalar_one_or_none()
    if queue is None:
        raise HTTPException(404, "Queue not found")

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
    tokens.sort(key=lambda t: (PRIORITY_ORDER.get(t.priority, 99), t.created_at, t.sequence))

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
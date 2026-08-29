"""Queue operations — create queue, token generation, automatic call-next,
priority elevation, listing.

Call-next is automatic: a prescription/order created for a visit is the
"consultation over" signal; complete_by_visit_id() is the trigger point.
Admin has manual overrides for edge cases only.
"""
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.business_date import get_business_date
from app.common.enums import OrderStatus, QueuePriority, QueueTokenStatus
from app.common.redis import department_channel, queue_channel
from app.departments.models import Department, Room
from app.inventory.models import InventoryItem
from app.notifications.models import NotificationHistory
from app.opd.models import Visit
from app.pathology.models import LabOrderItem
from app.patients.models import Patient
from app.pharmacy.models import Indent, IndentItem
from app.queue.models import Queue, QueueCounter, QueueToken, QueueTokenPriorityChange, Roster
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


def _patient_age(dob: date | None, age_years: int | None) -> int:
    if age_years is not None:
        return age_years
    if dob is None:
        return 0
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


async def get_doctor_worklist(
    db: AsyncSession,
    caller_user_id: uuid.UUID,
    caller_facility_id: uuid.UUID,
    caller_roles: list[str],
    token_id: uuid.UUID | None = None,
) -> list[dict]:
    """Return queue tokens joined to the minimum patient/visit context needed by OPD.

    A doctor only sees queues assigned to their own app user. Admins may inspect
    the facility worklist, but no caller can cross the facility boundary.
    """
    doctor = User.__table__.alias("queue_doctor")
    query = (
        select(
            QueueToken,
            Visit.patient_id,
            Patient.full_name,
            Patient.uhid,
            Patient.thid,
            Patient.age_years,
            Patient.dob,
            Patient.sex,
            Queue.doctor_user_id,
            doctor.c.full_name.label("provider_name"),
            Department.name.label("department_name"),
        )
        .join(Queue, Queue.id == QueueToken.queue_id)
        .join(Visit, Visit.id == QueueToken.visit_id)
        .join(Patient, Patient.id == Visit.patient_id)
        .join(doctor, doctor.c.id == Queue.doctor_user_id)
        .join(Department, Department.id == Queue.department_id)
        .where(Queue.facility_id == caller_facility_id)
        .order_by(QueueToken.priority_rank, QueueToken.created_at)
    )
    if "admin" not in caller_roles:
        query = query.where(Queue.doctor_user_id == caller_user_id)
    if token_id is not None:
        query = query.where(QueueToken.id == token_id)

    rows = (await db.execute(query)).all()
    return [
        {
            "id": token.id,
            "queue_id": token.queue_id,
            "visit_id": token.visit_id,
            "sequence": token.sequence,
            "token_display": token.token_display,
            "status": token.status,
            "priority": token.priority,
            "created_at": token.created_at,
            "called_at": token.called_at,
            "completed_at": token.completed_at,
            "patient_id": patient_id,
            "full_name": full_name,
            "uhid": uhid or thid or "—",
            "age_years": _patient_age(dob, age_years),
            "sex": sex,
            "provider_user_id": doctor_user_id,
            "provider_name": provider_name,
            "department": department_name,
        }
        for (
            token,
            patient_id,
            full_name,
            uhid,
            thid,
            age_years,
            dob,
            sex,
            doctor_user_id,
            provider_name,
            department_name,
        ) in rows
    ]


# ---------------- CALLER CONTEXT RESOLUTION ----------------
# resolve_caller_facility_id() lived here and did exactly what CurrentDbUser
# now does ΓÇö one extra users lookup per request to get facility_id from a
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

    doctor = await db.get(User, doctor_user_id)
    if (
        doctor is None
        or doctor.facility_id != caller_facility_id
        or not doctor.is_active
    ):
        raise HTTPException(404, "Doctor not found")

    if room_id is not None:
        room = await db.get(Room, room_id)
        if room is None or room.department_id != department_id or not room.is_active:
            raise HTTPException(422, "Select an active room in this department")
    
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


async def list_queue_opening_options(
    db: AsyncSession,
    caller_facility_id: uuid.UUID,
    service_date: date,
) -> list[dict]:
    """Available roster rows that do not already have a queue that day.

    Reception cannot list `/users` (correctly: it is an admin endpoint), and a
    UUID-only roster is not a usable doctor picker. This join exposes only the
    names and locations required to open a queue, scoped to the caller's
    facility and today's available roster.
    """
    rows = (
        await db.execute(
            select(
                Roster.id,
                Roster.staff_user_id,
                User.full_name,
                Roster.department_id,
                Department.name,
                Roster.room_id,
                Room.room_number,
                Roster.shift,
            )
            .join(User, User.id == Roster.staff_user_id)
            .join(Department, Department.id == Roster.department_id)
            .outerjoin(Room, Room.id == Roster.room_id)
            .outerjoin(
                Queue,
                and_(
                    Queue.doctor_user_id == Roster.staff_user_id,
                    Queue.department_id == Roster.department_id,
                    Queue.service_date == Roster.roster_date,
                ),
            )
            .where(
                Department.facility_id == caller_facility_id,
                Roster.roster_date == service_date,
                Roster.is_available.is_(True),
                User.is_active.is_(True),
                Queue.id.is_(None),
            )
            .order_by(Department.name, User.full_name, Roster.shift)
        )
    ).all()
    return [
        {
            "roster_id": roster_id,
            "staff_user_id": staff_user_id,
            "staff_name": staff_name,
            "department_id": department_id,
            "department_name": department_name,
            "room_id": room_id,
            "room_number": room_number,
            "shift": shift,
        }
        for (
            roster_id,
            staff_user_id,
            staff_name,
            department_id,
            department_name,
            room_id,
            room_number,
            shift,
        ) in rows
    ]


async def _allocate_token_number(db: AsyncSession, department_id: uuid.UUID, business_date: date) -> int:
    """Allocate the next token number for a department on a business date.

    One statement, no read-then-write. SELECT ... FOR UPDATE cannot lock a row
    that does not exist, so the first allocation of each day was a genuine race
    — and the IntegrityError fallback called db.rollback(), which ends the
    *caller's* transaction, not just the failed INSERT. create_token() calls
    this holding a lock on the queue row, so the observable failure was: two
    patients take the first token of the day at the same moment, one request
    500s, and that request's earlier work is discarded.

    Same pattern as app/common/accession.py and billing's
    _allocate_billing_number. Not gapless, and not required to be — a token
    number is a display label, not a financial document.
    """
    upsert = (
        pg_insert(QueueCounter.__table__)
        .values(department_id=department_id, counter_date=business_date, last_value=1)
        .on_conflict_do_update(
            constraint="uq_queue_counter_department_date",
            set_={"last_value": QueueCounter.__table__.c.last_value + 1},
        )
        .returning(QueueCounter.__table__.c.last_value)
    )
    return (await db.execute(upsert)).scalar_one()


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
    next_token.called_at = datetime.now(UTC)
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
        # The queue's facility, not the caller's — an admin acting across
        # facilities must not file this row under their own.
        facility_id=queue.facility_id,
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
    token.completed_at = datetime.now(UTC)
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
async def list_queues(
    db: AsyncSession,
    caller_facility_id: uuid.UUID,
    service_date: date,
    *,
    open_only: bool = True,
) -> list[dict]:
    """Today's queues at the caller's facility, with enough to choose one.

    POST /queue/tokens needs a queue_id and nothing let a receptionist discover
    one: /worklist is a doctor's own list and doctor/admin-only, and creating a
    queue is not the same as finding today's. So the token could only be issued
    by someone who already knew a UUID — which meant, in practice, that it could
    not be issued from a screen at all.

    Scoped to the caller's facility, and to one service_date: queues are unique
    per (department, doctor, service_date), so without the date filter a
    reception screen would offer yesterday's rows alongside today's.

    `waiting_count` is included because it is the number that decides which
    queue a walk-in should join, and asking the client to fetch tokens per
    queue to work it out would be a request per doctor on every page load.
    """
    stmt = select(Queue).where(
        Queue.facility_id == caller_facility_id,
        Queue.service_date == service_date,
    )
    if open_only:
        stmt = stmt.where(Queue.is_open.is_(True))

    queues = (await db.execute(stmt)).scalars().all()
    if not queues:
        return []

    # Resolved in two queries rather than two per queue — this is the first
    # screen of the day for the whole front desk.
    doctor_ids = {q.doctor_user_id for q in queues}
    room_ids = {q.room_id for q in queues if q.room_id}

    doctors = {
        u.id: u for u in (
            await db.execute(select(User).where(User.id.in_(doctor_ids)))
        ).scalars().all()
    }
    rooms = {
        r.id: r for r in (
            await db.execute(select(Room).where(Room.id.in_(room_ids)))
        ).scalars().all()
    } if room_ids else {}

    counts_result = await db.execute(
        select(QueueToken.queue_id, func.count())
        .where(
            QueueToken.queue_id.in_([q.id for q in queues]),
            QueueToken.status.in_(list(CALLABLE_STATUSES)),
        )
        .group_by(QueueToken.queue_id)
    )
    waiting_by_queue = dict(counts_result.all())

    now_serving_ids = [q.now_serving_token_id for q in queues if q.now_serving_token_id]
    now_serving_by_id: dict[uuid.UUID, str] = {}
    if now_serving_ids:
        now_serving_by_id = {
            t.id: t.token_display for t in (
                await db.execute(select(QueueToken).where(QueueToken.id.in_(now_serving_ids)))
            ).scalars().all()
        }

    rows = [
        {
            "id": q.id,
            "department_id": q.department_id,
            "doctor_user_id": q.doctor_user_id,
            "doctor_name": doctors[q.doctor_user_id].full_name if q.doctor_user_id in doctors else None,
            "room_id": q.room_id,
            "room_number": rooms[q.room_id].room_number if q.room_id in rooms else None,
            "display_label": q.display_label,
            "service_date": q.service_date,
            "is_open": q.is_open,
            "waiting_count": waiting_by_queue.get(q.id, 0),
            "now_serving": now_serving_by_id.get(q.now_serving_token_id) if q.now_serving_token_id else None,
        }
        for q in queues
    ]
    # Shortest queue first — the order a receptionist reads it in.
    rows.sort(key=lambda r: (r["waiting_count"], r["doctor_name"] or ""))
    return rows


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


# ---------------- ROSTER: CREATE (hod/admin only) ----------------
async def create_roster_entry(
    db: AsyncSession,
    staff_user_id: uuid.UUID,
    department_id: uuid.UUID,
    room_id: uuid.UUID | None,
    shift: str,
    roster_date: date,
    caller_facility_id: uuid.UUID,
    caller_roles: list[str],
    caller_department_id: uuid.UUID | None,
) -> Roster:
    if not ({"hod", "admin"} & set(caller_roles)):
        raise HTTPException(403, "Only hod or admin may assign roster entries")
    if "hod" in caller_roles and caller_department_id != department_id:
        raise HTTPException(403, "hod may only assign staff within their own department")
 
    department = await db.get(Department, department_id)
    if department is None or department.facility_id != caller_facility_id:
        raise HTTPException(404, "Department not found")

    staff = await db.get(User, staff_user_id)
    if staff is None or staff.facility_id != caller_facility_id:
        raise HTTPException(404, "Staff member not found")

    if room_id is not None:
        room = await db.get(Room, room_id)
        if room is None or room.department_id != department_id:
            raise HTTPException(404, "Room not found")
 
    entry = Roster(
        id=uuid.uuid4(),
        staff_user_id=staff_user_id,
        department_id=department_id,
        room_id=room_id,
        shift=shift,
        roster_date=roster_date,
    )
    db.add(entry)
    try:
        await db.flush()
    except IntegrityError as e:
        if getattr(e.orig, "sqlstate", None) == "23505":
            raise HTTPException(
                409,
                "This staff member already has a roster entry for this date/shift",
            ) from e
        raise
    await db.refresh(entry)
    return entry
 
 
# ---------------- ROSTER: LIST ----------------
async def list_roster(
    db: AsyncSession,
    department_id: uuid.UUID,
    roster_date: date,
    caller_facility_id: uuid.UUID,
) -> list[Roster]:
    department = await db.get(Department, department_id)
    if department is None or department.facility_id != caller_facility_id:
        raise HTTPException(404, "Department not found")
 
    result = await db.execute(
        select(Roster).where(
            Roster.department_id == department_id,
            Roster.roster_date == roster_date,
        )
    )
    return list(result.scalars().all())
 
 
# ---------------- ROSTER: AVAILABILITY (hod/admin only) ----------------
async def update_roster_availability(
    db: AsyncSession,
    roster_id: uuid.UUID,
    is_available: bool,
    caller_facility_id: uuid.UUID,
    caller_roles: list[str],
    caller_department_id: uuid.UUID | None,
) -> tuple[Roster, dict | None]:
    if not ({"hod", "admin"} & set(caller_roles)):
        raise HTTPException(403, "Only hod or admin may change availability")
 
    entry = await db.get(Roster, roster_id)
    if entry is None:
        raise HTTPException(404, "Roster entry not found")
 
    department = await db.get(Department, entry.department_id)
    if department is None or department.facility_id != caller_facility_id:
        raise HTTPException(404, "Roster entry not found")
 
    if "hod" in caller_roles and caller_department_id != entry.department_id:
        raise HTTPException(403, "hod may only act within their own department")
 
    entry.is_available = is_available
    await db.flush()
    await db.refresh(entry)
    #only notify the HOD when an ADMIN made this change
    pending_event = None
    if "hod" not in caller_roles and "admin" in caller_roles:
        staff = await db.get(User, entry.staff_user_id)
        payload = {
            "department_id": str(entry.department_id),
            "roster_id": str(entry.id),
            "staff_name": staff.full_name if staff else None,
            "shift": entry.shift,
            "roster_date": entry.roster_date.isoformat(),
            "is_available": is_available,
        }
        db.add(NotificationHistory(
            id=uuid.uuid4(),
            event_type="roster_availability_changed",
            payload=payload,
            department_id=entry.department_id,
            # The department's facility, not the caller's — an admin may act
            # across facilities and must not file this under their own.
            facility_id=department.facility_id,
        ))
        await db.flush()
        pending_event = {
            "channel": department_channel(entry.department_id),
            "event_type": "roster_availability_changed",
            "payload": payload,
        }
 
    return entry, pending_event
 
 
# ---------------- QUEUE: PAUSE / RESUME (hod/admin only) ----------------
async def _set_queue_open_state(
    db: AsyncSession,
    queue_id: uuid.UUID,
    is_open: bool,
    caller_facility_id: uuid.UUID,
    caller_roles: list[str],
    caller_department_id: uuid.UUID | None,
) -> tuple[Queue, dict | None]:
    """Pausing doesn't touch a token already CALLED -- that patient still
    gets seen. On resume, _find_unresolved_called_token() blocks further
    advancement until that token is completed. Intentional, not a gap.
    """
    if not ({"hod", "admin"} & set(caller_roles)):
        raise HTTPException(403, "Only hod or admin may pause or resume a queue")
 
    queue = await _get_scoped_queue(db, queue_id, caller_facility_id, for_update=True)
 
    if "hod" in caller_roles and caller_department_id != queue.department_id:
        raise HTTPException(403, "hod may only act within their own department")
 
    queue.is_open = is_open
    await db.flush()
    await db.refresh(queue)
 
    # HOD notify cascade: reuses the notifications SSE plumbing from task 6.
    doctor = await db.get(User, queue.doctor_user_id)
    payload = {
        "department_id": str(queue.department_id),
        "queue_id": str(queue.id),
        "doctor_name": doctor.full_name if doctor else None,
        "is_open": is_open,
    }
    event_type = "queue_resumed" if is_open else "queue_paused"
    db.add(NotificationHistory(
        id=uuid.uuid4(),
        event_type=event_type,
        payload=payload,
        department_id=queue.department_id,
        facility_id=queue.facility_id,
    ))
    await db.flush()
 
    pending_event = {
        "channel": department_channel(queue.department_id),
        "event_type": event_type,
        "payload": payload,
    }
    return queue, pending_event
 
 
async def pause_queue(
    db: AsyncSession,
    queue_id: uuid.UUID,
    caller_facility_id: uuid.UUID,
    caller_roles: list[str],
    caller_department_id: uuid.UUID | None,
) -> tuple[Queue, dict | None]:
    return await _set_queue_open_state(
        db, queue_id, False, caller_facility_id, caller_roles, caller_department_id
    )
 
 
async def resume_queue(
    db: AsyncSession,
    queue_id: uuid.UUID,
    caller_facility_id: uuid.UUID,
    caller_roles: list[str],
    caller_department_id: uuid.UUID | None,
) -> tuple[Queue, dict | None]:
    return await _set_queue_open_state(
        db, queue_id, True, caller_facility_id, caller_roles, caller_department_id
    )


# ---------------- HOD DASHBOARD: OVERVIEW ----------------
async def get_hod_dashboard_overview(
    db: AsyncSession,
    department_id: uuid.UUID,
    overview_date: date,
    caller_facility_id: uuid.UUID,
) -> dict:
    department = await db.get(Department, department_id)
    if department is None or department.facility_id != caller_facility_id:
        raise HTTPException(404, "Department not found")
 
    queues_result = await db.execute(
        select(Queue).where(
            Queue.department_id == department_id,
            Queue.service_date == overview_date,
        )
    )
    queues = list(queues_result.scalars().all())
 
    queue_summaries = []
    for queue in queues:
        result = await list_queue_tokens(db, queue.id, caller_facility_id)
        doctor = await db.get(User, queue.doctor_user_id)
        queue_summaries.append({
            "queue_id": queue.id,
            "doctor_user_id": queue.doctor_user_id,
            "doctor_name": doctor.full_name if doctor else None,
            "room_id": queue.room_id,
            "is_open": queue.is_open,
            "waiting_count": result["waiting_count"],
            "now_serving": result["now_serving"],
        })
 
    roster_entries = await list_roster(db, department_id, overview_date, caller_facility_id)
 
    return {
        "department_id": department_id,
        "date": overview_date,
        "queues": queue_summaries,
        "roster": [
            {
                "roster_id": r.id,
                "staff_user_id": r.staff_user_id,
                "shift": r.shift,
                "room_id": r.room_id,
                "is_available": r.is_available,
            }
            for r in roster_entries
        ],
    }


 # ---------------- HOD DASHBOARD: PENDING LAB ORDERS ----------------
async def get_pending_lab_orders(
    db: AsyncSession,
    department_id: uuid.UUID,
    caller_facility_id: uuid.UUID,
) -> list[dict]:
    """radiology_order_items has no department_id column (unlike
    lab_order_items) -- flagged separately, not included here yet."""
    department = await db.get(Department, department_id)
    if department is None or department.facility_id != caller_facility_id:
        raise HTTPException(404, "Department not found")
 
    result = await db.execute(
        select(LabOrderItem).where(
            LabOrderItem.department_id == department_id,
            LabOrderItem.status.notin_([OrderStatus.COMPLETED.value, OrderStatus.CANCELLED.value]),
        )
    )
    items = result.scalars().all()
 
    return [
        {
            "lab_order_item_id": item.id,
            "accession_number": item.accession_number,
            "test_name": item.test_name,
            "status": item.status,
            "estimated_minutes": item.estimated_minutes,
            "created_at": item.created_at,
        }
        for item in items
    ]


# ---------------- HOD DASHBOARD: REASSIGN TOKEN (hod/admin only) ----------------
async def reassign_token(
    db: AsyncSession,
    token_id: uuid.UUID,
    target_queue_id: uuid.UUID,
    caller_facility_id: uuid.UUID,
    caller_roles: list[str],
    caller_department_id: uuid.UUID | None,
) -> QueueToken:
    """Moves a waiting patient to a different doctor's queue. The old
    token is marked transferred (kept as a permanent record, not
    deleted); a new token is created in the target queue with the same
    visit_id, token_display, and priority -- only the queue (and
    therefore doctor) changes. Matches the existing comment on
    queue_tokens: "a token can be moved to another doctor (transferred)
    without reprinting the number."
    """
    if not ({"hod", "admin"} & set(caller_roles)):
        raise HTTPException(403, "Only hod or admin may reassign a token")
 
    token, source_queue = await _get_scoped_token(db, token_id, caller_facility_id, for_update=True)
 
    if token.status != QueueTokenStatus.WAITING.value:
        raise HTTPException(409, f"Cannot reassign a token with status '{token.status}'")
 
    target_queue = await _get_scoped_queue(db, target_queue_id, caller_facility_id, for_update=True)
 
    if target_queue.department_id != source_queue.department_id:
        raise HTTPException(422, "Can only reassign within the same department")
 
    if "hod" in caller_roles and caller_department_id != source_queue.department_id:
        raise HTTPException(403, "hod may only act within their own department")
 
    if target_queue.id == source_queue.id:
        raise HTTPException(422, "Token is already in this queue")
 
    token.status = QueueTokenStatus.TRANSFERRED.value
 
    next_seq_expr = func.coalesce(func.max(QueueToken.sequence), 0) + 1  # pr-check: ignore
    next_seq = (
        await db.execute(select(next_seq_expr).where(QueueToken.queue_id == target_queue_id))
    ).scalar_one()
 
    new_token = QueueToken(
        id=uuid.uuid4(),
        facility_id=target_queue.facility_id,
        queue_id=target_queue_id,
        visit_id=token.visit_id,
        sequence=next_seq,
        token_display=token.token_display,
        initial_priority=token.initial_priority,
        status=QueueTokenStatus.WAITING.value,
        priority=token.priority,
        priority_rank=token.priority_rank,
    )
    db.add(new_token)
    await db.flush()
    await db.refresh(new_token)
    return new_token


_ELEVATION_ALERT_THRESHOLD = 5  # per §schema: ">5/day by one user is an alert, not a block"
 
 
# ---------------- HOD DASHBOARD: PRIORITY ELEVATION ALERTS ----------------
async def get_priority_elevation_alerts(
    db: AsyncSession,
    department_id: uuid.UUID,
    alert_date: date,
    caller_facility_id: uuid.UUID,
) -> list[dict]:
    """Flags any user who changed >5 token priorities on this date, for
    this department -- matches the schema's documented abuse-detection
    rule exactly. Day boundary is a plain UTC calendar day here, not the
    facility-timezone business date used elsewhere for token numbering --
    acceptable for a monitoring signal, not something patient-facing or
    financial."""
    department = await db.get(Department, department_id)
    if department is None or department.facility_id != caller_facility_id:
        raise HTTPException(404, "Department not found")
 
    day_start = datetime.combine(alert_date, datetime.min.time(), tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
 
    result = await db.execute(
        select(QueueTokenPriorityChange.changed_by, func.count(QueueTokenPriorityChange.id))
        .join(QueueToken, QueueToken.id == QueueTokenPriorityChange.queue_token_id)
        .join(Queue, Queue.id == QueueToken.queue_id)
        .where(
            Queue.department_id == department_id,
            QueueTokenPriorityChange.changed_at >= day_start,
            QueueTokenPriorityChange.changed_at < day_end,
        )
        .group_by(QueueTokenPriorityChange.changed_by)
        .having(func.count(QueueTokenPriorityChange.id) > _ELEVATION_ALERT_THRESHOLD)
    )
 
    alerts = []
    for changed_by, count in result.all():
        user = await db.get(User, changed_by)
        alerts.append({
            "user_id": changed_by,
            "user_name": user.full_name if user else None,
            "elevation_count": count,
            "date": alert_date,
        })
    return alerts


 # ---------------- HOD DASHBOARD: DEPARTMENT WORKLOAD ----------------
async def get_department_workload(
    db: AsyncSession,
    department_id: uuid.UUID,
    workload_date: date,
    caller_facility_id: uuid.UUID,
) -> dict:
    """DRAFT scope -- the schema/architecture docs list "department
    workload" and "doctor consultation load" as report categories but
    don't specify exact fields. This covers what's directly computable
    from existing queue/token data: total waiting, open vs closed
    queues, and completed-today as a throughput signal. Flag to tech
    lead if a different shape is wanted."""
    department = await db.get(Department, department_id)
    if department is None or department.facility_id != caller_facility_id:
        raise HTTPException(404, "Department not found")
 
    queues_result = await db.execute(
        select(Queue).where(
            Queue.department_id == department_id,
            Queue.service_date == workload_date,
        )
    )
    queues = list(queues_result.scalars().all())
    queue_ids = [q.id for q in queues]
 
    open_count = sum(1 for q in queues if q.is_open)
    closed_count = len(queues) - open_count
 
    if not queue_ids:
        return {
            "department_id": department_id,
            "date": workload_date,
            "total_waiting": 0,
            "queues_open": 0,
            "queues_closed": 0,
            "completed_today": 0,
        }
 
    waiting_result = await db.execute(
        select(func.count(QueueToken.id)).where(
            QueueToken.queue_id.in_(queue_ids),
            QueueToken.status.in_(CALLABLE_STATUSES),
        )
    )
    total_waiting = waiting_result.scalar_one()
 
    completed_result = await db.execute(
        select(func.count(QueueToken.id)).where(
            QueueToken.queue_id.in_(queue_ids),
            QueueToken.status == QueueTokenStatus.COMPLETED.value,
        )
    )
    completed_today = completed_result.scalar_one()
 
    return {
        "department_id": department_id,
        "date": workload_date,
        "total_waiting": total_waiting,
        "queues_open": open_count,
        "queues_closed": closed_count,
        "completed_today": completed_today,
    }


 # ---------------- HOD DASHBOARD: EMERGENCY ESCALATIONS ----------------
async def get_emergency_escalations(
    db: AsyncSession,
    department_id: uuid.UUID,
    caller_facility_id: uuid.UUID,
) -> list[dict]:
    """DRAFT scope -- "emergency escalations" isn't defined precisely
    anywhere in the schema/architecture docs (checked both directly).
    This surfaces currently-active emergency-priority tokens (waiting or
    called, not yet resolved) for the department, so the HOD can see at
    a glance which critical cases are in play right now. Flag to tech
    lead if a different shape is wanted -- e.g. a durable escalation log
    rather than a live snapshot."""
    department = await db.get(Department, department_id)
    if department is None or department.facility_id != caller_facility_id:
        raise HTTPException(404, "Department not found")
 
    rows = (await db.execute(
        select(QueueToken, User.full_name.label("doctor_name"))
        .join(Queue, Queue.id == QueueToken.queue_id)
        .outerjoin(User, User.id == Queue.doctor_user_id)
        .where(
            Queue.department_id == department_id,
            QueueToken.priority == QueuePriority.EMERGENCY.value,
            QueueToken.status.in_([QueueTokenStatus.WAITING.value, QueueTokenStatus.CALLED.value]),
        )
    )).all()

    return [
        {
            "token_id": token.id,
            "token_display": token.token_display,
            "status": token.status,
            "doctor_name": doctor_name,
            "created_at": token.created_at,
        }
        for token, doctor_name in rows
    ]
 
# ---------------- HOD DASHBOARD: PENDING APPROVALS (indents) ----------------
async def get_pending_approvals(
    db: AsyncSession,
    department_id: uuid.UUID,
    caller_facility_id: uuid.UUID,
) -> list[dict]:
    """"Pending approvals" maps to indent approval per the HOD role
    table -- an indent still in status='requested' is waiting on a
    HOD/admin decision. Includes the requested items so the HOD can see
    what's actually being asked for, not just that something is
    pending."""
    department = await db.get(Department, department_id)
    if department is None or department.facility_id != caller_facility_id:
        raise HTTPException(404, "Department not found")
 
    rows = (await db.execute(
        select(Indent, IndentItem, InventoryItem.name.label("item_name"))
        .outerjoin(IndentItem, IndentItem.indent_id == Indent.id)
        .outerjoin(InventoryItem, InventoryItem.id == IndentItem.item_id)
        .where(
            Indent.department_id == department_id,
            Indent.status == "requested",
        )
        .order_by(Indent.created_at.desc(), IndentItem.id)
    )).all()

    approvals_by_id: dict[uuid.UUID, dict] = {}
    for indent, item, item_name in rows:
        approval = approvals_by_id.setdefault(indent.id, {
            "indent_id": indent.id,
            "department_id": indent.department_id,
            "created_at": indent.created_at,
            "items": [],
        })
        if item is not None:
            approval["items"].append({
                "item_id": item.item_id,
                "item_name": item_name,
                "quantity_requested": item.quantity_requested,
            })

    return list(approvals_by_id.values())

"""Appointments business logic — scheduling, conflict checking, check-in."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.appointments.models import Appointment, AppointmentService
from app.appointments.schemas import (
    AppointmentCheckInRequest,
    AppointmentCheckInResult,
    AppointmentCreate,
    AppointmentServiceCreate,
    AppointmentUpdate,
)
from app.common.enums import VisitType
from app.departments.models import Department
from app.opd.models import Visit
from app.opd.schemas import VisitCreate
from app.opd.service import create_visit
from app.patients.models import Patient
from app.queue.models import Queue, QueueToken
from app.queue.service import create_token
from app.users.models import User


class AppointmentConflictError(Exception):
    """Raised when a doctor already has an active appointment in the requested slot."""
    pass


class AppointmentNotFoundError(Exception):
    """Raised when an appointment, or an id it references, is not in the caller's facility."""
    pass


class AppointmentValidationError(Exception):
    """Raised for a request that is well-formed but cannot be scheduled (422)."""
    pass


class AppointmentStateError(Exception):
    """Raised when the appointment's current status does not allow the change (409)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


#: Statuses that still hold a slot in the doctor's day.
ACTIVE_STATUSES = frozenset({"booked", "confirmed", "checked_in"})

#: Status changes PATCH may make. Check-in has its own endpoint because it
#: creates a visit; `rescheduled` stays in the CHECK for history but a
#: reschedule edits the booking in place instead of moving it to a new row.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "booked": frozenset({"confirmed", "cancelled", "no_show"}),
    "confirmed": frozenset({"cancelled", "no_show"}),
    "checked_in": frozenset({"completed"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
    "no_show": frozenset(),
    "rescheduled": frozenset(),
}

RESCHEDULABLE_STATUSES = frozenset({"booked", "confirmed"})
CHECK_IN_STATUSES = frozenset({"booked", "confirmed"})


def calc_end_time(start_time_str: str, duration_minutes: int) -> str:
    """End of the slot as HH:MM. A slot must end on the day it starts: the
    overlap check compares HH:MM strings, which cannot order a slot that
    wraps past midnight."""
    hours, minutes = (int(part) for part in start_time_str.split(":"))
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise AppointmentValidationError(f"Invalid start time '{start_time_str}'")
    start = datetime(2000, 1, 1, hours, minutes)
    end = start + timedelta(minutes=duration_minutes)
    if end.date() != start.date():
        raise AppointmentValidationError("An appointment must end on the day it starts")
    return f"{end.hour:02d}:{end.minute:02d}"


async def _facility_today(db: AsyncSession, facility_id: uuid.UUID) -> date:
    from app.common.patient_scope import facility_today

    return await facility_today(db, facility_id)


async def _require_patient(db: AsyncSession, patient_id: uuid.UUID, facility_id: uuid.UUID) -> None:
    found = (await db.execute(select(Patient.id).where(
        Patient.id == patient_id,
        Patient.facility_id == facility_id,
        Patient.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if found is None:
        raise AppointmentNotFoundError("Patient not found")


async def _require_department(db: AsyncSession, department_id: uuid.UUID, facility_id: uuid.UUID) -> None:
    found = (await db.execute(select(Department.id).where(
        Department.id == department_id, Department.facility_id == facility_id,
    ))).scalar_one_or_none()
    if found is None:
        raise AppointmentNotFoundError("Department not found")


async def _lock_doctor(db: AsyncSession, doctor_user_id: uuid.UUID, facility_id: uuid.UUID) -> None:
    """Load the doctor under FOR UPDATE. Two bookings for the same doctor then
    serialise here, so the overlap check that follows cannot race: locking the
    existing appointment rows would not stop a second insert into an empty slot."""
    found = (await db.execute(
        select(User.id)
        .where(User.id == doctor_user_id, User.facility_id == facility_id, User.is_active.is_(True))
        .with_for_update()
    )).scalar_one_or_none()
    if found is None:
        raise AppointmentNotFoundError("Doctor not found")


async def _require_service(
    db: AsyncSession, service_id: uuid.UUID, facility_id: uuid.UUID
) -> AppointmentService:
    svc = (await db.execute(select(AppointmentService).where(
        AppointmentService.id == service_id,
        AppointmentService.facility_id == facility_id,
        AppointmentService.is_active.is_(True),
    ))).scalar_one_or_none()
    if svc is None:
        raise AppointmentNotFoundError("Service not found")
    return svc


async def _require_follow_up_visit(
    db: AsyncSession, visit_id: uuid.UUID, patient_id: uuid.UUID, facility_id: uuid.UUID
) -> None:
    found = (await db.execute(select(Visit.id).where(
        Visit.id == visit_id, Visit.patient_id == patient_id, Visit.facility_id == facility_id,
    ))).scalar_one_or_none()
    if found is None:
        raise AppointmentNotFoundError("Follow-up visit not found for this patient")


async def _check_conflict(
    db: AsyncSession,
    facility_id: uuid.UUID,
    doctor_user_id: uuid.UUID,
    appointment_date: date,
    start_time: str,
    end_time: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    stmt = select(Appointment).where(
        Appointment.facility_id == facility_id,
        Appointment.doctor_user_id == doctor_user_id,
        Appointment.appointment_date == appointment_date,
        Appointment.status.in_(ACTIVE_STATUSES),
        Appointment.start_time < end_time,
        Appointment.end_time > start_time,
    )
    if exclude_id is not None:
        stmt = stmt.where(Appointment.id != exclude_id)
    conflict = (await db.execute(stmt.limit(1))).scalars().first()
    if conflict is not None:
        raise AppointmentConflictError(
            f"Doctor already has an appointment scheduled between {conflict.start_time} and {conflict.end_time}"
        )


async def list_services(
    db: AsyncSession, facility_id: uuid.UUID
) -> list[AppointmentService]:
    stmt = (
        select(AppointmentService)
        .where(
            AppointmentService.facility_id == facility_id,
            AppointmentService.is_active.is_(True),
        )
        .order_by(AppointmentService.name)
    )
    return list((await db.execute(stmt)).scalars().all())


async def create_service(
    db: AsyncSession, facility_id: uuid.UUID, payload: AppointmentServiceCreate
) -> AppointmentService:
    if payload.department_id is not None:
        await _require_department(db, payload.department_id, facility_id)
    service = AppointmentService(
        facility_id=facility_id,
        department_id=payload.department_id,
        name=payload.name,
        name_hi=payload.name_hi,
        duration_minutes=payload.duration_minutes,
        description=payload.description,
        is_active=True,
    )
    db.add(service)
    await db.flush()
    await db.refresh(service)
    return service


async def list_appointments(
    db: AsyncSession,
    facility_id: uuid.UUID,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    department_id: uuid.UUID | None = None,
    doctor_user_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    status: str | None = None,
    appointment_id: uuid.UUID | None = None,
) -> list[dict]:
    # The joined patient and department are scoped too: an appointment row that
    # points across facilities must not carry another facility's name here.
    filters = [
        Appointment.facility_id == facility_id,
        Patient.facility_id == facility_id,
        Department.facility_id == facility_id,
    ]
    if date_from is not None:
        filters.append(Appointment.appointment_date >= date_from)
    if date_to is not None:
        filters.append(Appointment.appointment_date <= date_to)
    if department_id is not None:
        filters.append(Appointment.department_id == department_id)
    if doctor_user_id is not None:
        filters.append(Appointment.doctor_user_id == doctor_user_id)
    if patient_id is not None:
        filters.append(Appointment.patient_id == patient_id)
    if status is not None:
        filters.append(Appointment.status == status)
    if appointment_id is not None:
        filters.append(Appointment.id == appointment_id)

    stmt = (
        select(
            Appointment,
            Patient.full_name.label("patient_name"),
            Patient.uhid.label("patient_uhid"),
            User.full_name.label("doctor_name"),
            Department.name.label("department_name"),
            Department.name_hi.label("department_name_hi"),
        )
        .join(Patient, Patient.id == Appointment.patient_id)
        .join(Department, Department.id == Appointment.department_id)
        .outerjoin(User, User.id == Appointment.doctor_user_id)
        .where(*filters)
        .order_by(Appointment.appointment_date, Appointment.start_time)
    )

    rows = (await db.execute(stmt)).all()
    results = []
    for appt, patient_name, patient_uhid, doctor_name, department_name, department_name_hi in rows:
        d = {
            "id": appt.id,
            "facility_id": appt.facility_id,
            "patient_id": appt.patient_id,
            "department_id": appt.department_id,
            "doctor_user_id": appt.doctor_user_id,
            "service_id": appt.service_id,
            "service_name": appt.service_name,
            "duration_minutes": appt.duration_minutes,
            "appointment_date": appt.appointment_date,
            "start_time": appt.start_time,
            "end_time": appt.end_time,
            "status": appt.status,
            "is_walk_in": appt.is_walk_in,
            "is_teleconsult": appt.is_teleconsult,
            "teleconsult_status": appt.teleconsult_status,
            "notes": appt.notes,
            "follow_up_from_visit_id": appt.follow_up_from_visit_id,
            "visit_id": appt.visit_id,
            "token_id": appt.token_id,
            "cancellation_reason": appt.cancellation_reason,
            "created_at": appt.created_at,
            "patient_name": patient_name,
            "patient_uhid": patient_uhid,
            "doctor_name": doctor_name,
            "department_name": department_name,
            "department_name_hi": department_name_hi,
        }
        results.append(d)
    return results


async def get_appointment_detail(
    db: AsyncSession, facility_id: uuid.UUID, appointment_id: uuid.UUID
) -> dict:
    rows = await list_appointments(db, facility_id, appointment_id=appointment_id)
    if not rows:
        raise AppointmentNotFoundError(f"Appointment {appointment_id} not found")
    return rows[0]


async def get_appointment(
    db: AsyncSession, facility_id: uuid.UUID, appointment_id: uuid.UUID, *, for_update: bool = False
) -> Appointment:
    stmt = select(Appointment).where(
        Appointment.id == appointment_id, Appointment.facility_id == facility_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    appt = (await db.execute(stmt)).scalar_one_or_none()
    if appt is None:
        raise AppointmentNotFoundError(f"Appointment {appointment_id} not found")
    return appt


async def create_appointment(
    db: AsyncSession,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
    payload: AppointmentCreate,
) -> Appointment:
    await _require_patient(db, payload.patient_id, facility_id)
    await _require_department(db, payload.department_id, facility_id)
    if payload.follow_up_from_visit_id is not None:
        await _require_follow_up_visit(db, payload.follow_up_from_visit_id, payload.patient_id, facility_id)

    service_name = payload.service_name
    duration = payload.duration_minutes
    if payload.service_id is not None:
        # The catalogue row is the authority for what was booked and how long it takes.
        svc = await _require_service(db, payload.service_id, facility_id)
        service_name = svc.name
        duration = svc.duration_minutes

    if payload.appointment_date < await _facility_today(db, facility_id):
        raise AppointmentValidationError("An appointment cannot be booked for a past date")
    end_time = calc_end_time(payload.start_time, duration)

    if payload.doctor_user_id is not None:
        await _lock_doctor(db, payload.doctor_user_id, facility_id)
        await _check_conflict(
            db, facility_id, payload.doctor_user_id, payload.appointment_date, payload.start_time, end_time,
        )

    teleconsult_status = (
        "video_delivery_unavailable" if payload.is_teleconsult else None
    )

    appt = Appointment(
        id=uuid.uuid4(),
        facility_id=facility_id,
        patient_id=payload.patient_id,
        department_id=payload.department_id,
        doctor_user_id=payload.doctor_user_id,
        service_id=payload.service_id,
        service_name=service_name,
        duration_minutes=duration,
        appointment_date=payload.appointment_date,
        start_time=payload.start_time,
        end_time=end_time,
        status="booked",
        is_walk_in=payload.is_walk_in,
        is_teleconsult=payload.is_teleconsult,
        teleconsult_status=teleconsult_status,
        notes=payload.notes,
        follow_up_from_visit_id=payload.follow_up_from_visit_id,
        created_by=actor_id,
    )
    db.add(appt)
    await db.flush()
    await db.refresh(appt)
    return appt


async def update_appointment(
    db: AsyncSession,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
    appointment_id: uuid.UUID,
    payload: AppointmentUpdate,
) -> Appointment:
    appt = await get_appointment(db, facility_id, appointment_id, for_update=True)

    reschedule = any(
        value is not None
        for value in (payload.appointment_date, payload.start_time, payload.duration_minutes, payload.doctor_user_id)
    )
    if reschedule:
        if appt.status not in RESCHEDULABLE_STATUSES:
            raise AppointmentStateError(
                "appointment_not_reschedulable",
                f"A {appt.status} appointment cannot be rescheduled",
            )
        new_date = payload.appointment_date or appt.appointment_date
        new_start = payload.start_time or appt.start_time
        new_duration = payload.duration_minutes or appt.duration_minutes
        new_doctor = payload.doctor_user_id or appt.doctor_user_id
        if new_date < await _facility_today(db, facility_id):
            raise AppointmentValidationError("An appointment cannot be moved to a past date")
        new_end = calc_end_time(new_start, new_duration)
        if new_doctor is not None:
            await _lock_doctor(db, new_doctor, facility_id)
            await _check_conflict(db, facility_id, new_doctor, new_date, new_start, new_end, exclude_id=appt.id)
        appt.appointment_date = new_date
        appt.start_time = new_start
        appt.duration_minutes = new_duration
        appt.end_time = new_end
        appt.doctor_user_id = new_doctor

    if payload.status is not None and payload.status != appt.status:
        if payload.status not in ALLOWED_TRANSITIONS.get(appt.status, frozenset()):
            raise AppointmentStateError(
                "invalid_appointment_transition",
                f"Cannot change a {appt.status} appointment to {payload.status}",
            )
        if payload.status == "cancelled" and not (payload.cancellation_reason or "").strip():
            raise AppointmentValidationError("A cancellation reason is required")
        appt.status = payload.status
    if payload.cancellation_reason is not None:
        appt.cancellation_reason = payload.cancellation_reason.strip() or None
    if payload.notes is not None:
        appt.notes = payload.notes

    appt.updated_by = actor_id
    await db.flush()
    await db.refresh(appt)
    return appt


async def _resolve_check_in_queue(
    db: AsyncSession, appt: Appointment, facility_id: uuid.UUID, service_date: date
) -> tuple[uuid.UUID | None, str | None]:
    """Today's open queue for the booked doctor, or the department's only open
    queue. Returns (queue_id, None) or (None, reason) — never a guess between
    several doctors' queues."""
    stmt = select(Queue.id, Queue.doctor_user_id).where(
        Queue.facility_id == facility_id,
        Queue.department_id == appt.department_id,
        Queue.service_date == service_date,
        Queue.is_open.is_(True),
    )
    rows = (await db.execute(stmt)).all()
    if appt.doctor_user_id is not None:
        for queue_id, doctor_id in rows:
            if doctor_id == appt.doctor_user_id:
                return queue_id, None
    if len(rows) == 1:
        return rows[0][0], None
    if not rows:
        return None, "no_open_queue"
    return None, "multiple_open_queues"


def _token_error_reason(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return str(detail.get("code") or detail.get("message") or "token_not_issued")
    return str(detail)


async def check_in_appointment(
    db: AsyncSession,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
    appointment_id: uuid.UUID,
    payload: AppointmentCheckInRequest,
    facility_code: str,
    facility_timezone: str,
) -> AppointmentCheckInResult:
    # The row lock makes a double-clicked check-in wait for the first one and
    # then take the re-entry branch below instead of opening a second visit.
    appt = await get_appointment(db, facility_id, appointment_id, for_update=True)

    if appt.visit_id is not None:
        existing_visit = await db.get(Visit, appt.visit_id)
        existing_token = await db.get(QueueToken, appt.token_id) if appt.token_id else None
        return AppointmentCheckInResult(
            appointment_id=appt.id,
            status=appt.status,
            visit_id=appt.visit_id,
            visit_number=existing_visit.visit_number if existing_visit else "",
            token_id=existing_token.id if existing_token else None,
            token_display=existing_token.token_display if existing_token else None,
            token_status="issued" if existing_token else "not_issued",
            token_not_issued_reason=None if existing_token else "no_token_at_check_in",
        )

    if appt.status not in CHECK_IN_STATUSES:
        raise AppointmentStateError(
            "appointment_not_checkable",
            f"A {appt.status} appointment cannot be checked in",
        )
    today = datetime.now(ZoneInfo(facility_timezone)).date()
    if appt.appointment_date != today:
        raise AppointmentStateError(
            "appointment_not_today",
            f"This appointment is for {appt.appointment_date.isoformat()}, not today",
        )

    visit_type = "teleconsult" if appt.is_teleconsult else "opd"
    visit_create = VisitCreate(
        patient_id=appt.patient_id,
        department_id=appt.department_id,
        visit_type=visit_type,
        visit_date=datetime.now(ZoneInfo(facility_timezone)),
    )
    visit = await create_visit(
        db,
        payload=visit_create,
        facility_code=facility_code,
        facility_timezone=facility_timezone,
        created_by=actor_id,
        facility_id=facility_id,
    )

    token: QueueToken | None = None
    reason: str | None = None
    if visit_type not in VisitType.token_issuing():
        reason = "visit_type_not_queued"
    else:
        queue_id = payload.queue_id
        if queue_id is None:
            queue_id, reason = await _resolve_check_in_queue(db, appt, facility_id, today)
        if queue_id is not None:
            # A refused token (closed queue, bad priority) must not undo the
            # visit the patient is now standing at the desk for. The savepoint
            # rolls back only the token; the desk is told it was not issued.
            try:
                async with db.begin_nested():
                    token = await create_token(
                        db,
                        queue_id=queue_id,
                        visit_id=visit.id,
                        priority=payload.priority,
                        caller_facility_id=facility_id,
                    )
            except HTTPException as exc:
                token = None
                reason = _token_error_reason(exc)

    appt.status = "checked_in"
    appt.visit_id = visit.id
    appt.token_id = token.id if token else None
    appt.updated_by = actor_id
    await db.flush()

    return AppointmentCheckInResult(
        appointment_id=appt.id,
        status=appt.status,
        visit_id=visit.id,
        visit_number=visit.visit_number,
        token_id=token.id if token else None,
        token_display=token.token_display if token else None,
        token_status="issued" if token else "not_issued",
        token_not_issued_reason=reason,
    )

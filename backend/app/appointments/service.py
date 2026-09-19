"""Appointments business logic — scheduling, conflict checking, check-in."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.appointments.models import Appointment, AppointmentService
from app.appointments.schemas import (
    AppointmentCheckInRequest,
    AppointmentCheckInResult,
    AppointmentCreate,
    AppointmentServiceCreate,
    AppointmentUpdate,
)
from app.departments.models import Department
from app.opd.models import Visit
from app.opd.schemas import VisitCreate
from app.opd.service import create_visit
from app.patients.models import Patient
from app.queue.models import QueueToken
from app.queue.service import create_token
from app.users.models import User


class AppointmentConflictError(Exception):
    """Raised when a doctor already has an active appointment in the requested slot."""
    pass


class AppointmentNotFoundError(Exception):
    """Raised when an appointment is not found."""
    pass


def calc_end_time(start_time_str: str, duration_minutes: int) -> str:
    parts = start_time_str.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    dt = datetime(2000, 1, 1, hours, minutes) + timedelta(minutes=duration_minutes)
    return f"{dt.hour:02d}:{dt.minute:02d}"


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
    service = AppointmentService(
        facility_id=facility_id,
        department_id=payload.department_id,
        name=payload.name,
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
) -> list[dict]:
    filters = [Appointment.facility_id == facility_id]
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

    stmt = (
        select(
            Appointment,
            Patient.full_name.label("patient_name"),
            Patient.uhid.label("patient_uhid"),
            User.full_name.label("doctor_name"),
            Department.name.label("department_name"),
        )
        .join(Patient, Patient.id == Appointment.patient_id)
        .join(Department, Department.id == Appointment.department_id)
        .outerjoin(User, User.id == Appointment.doctor_user_id)
        .where(*filters)
        .order_by(Appointment.appointment_date, Appointment.start_time)
    )

    rows = (await db.execute(stmt)).all()
    results = []
    for appt, patient_name, patient_uhid, doctor_name, department_name in rows:
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
        }
        results.append(d)
    return results


async def get_appointment(
    db: AsyncSession, facility_id: uuid.UUID, appointment_id: uuid.UUID
) -> Appointment:
    appt = await db.get(Appointment, appointment_id)
    if not appt or appt.facility_id != facility_id:
        raise AppointmentNotFoundError(f"Appointment {appointment_id} not found")
    return appt


async def create_appointment(
    db: AsyncSession,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
    payload: AppointmentCreate,
) -> Appointment:
    end_time = calc_end_time(payload.start_time, payload.duration_minutes)

    # Conflict prevention: Check if doctor has overlapping active appointment
    if payload.doctor_user_id is not None:
        conflict_stmt = select(Appointment).where(
            Appointment.facility_id == facility_id,
            Appointment.doctor_user_id == payload.doctor_user_id,
            Appointment.appointment_date == payload.appointment_date,
            Appointment.status.in_(["booked", "confirmed", "checked_in"]),
            Appointment.start_time < end_time,
            Appointment.end_time > payload.start_time,
        )
        conflicts = (await db.execute(conflict_stmt)).scalars().all()
        if conflicts:
            raise AppointmentConflictError(
                f"Doctor already has an appointment scheduled between {conflicts[0].start_time} and {conflicts[0].end_time}"
            )

    teleconsult_status = (
        "video_delivery_unavailable" if payload.is_teleconsult else None
    )

    appt = Appointment(
        facility_id=facility_id,
        patient_id=payload.patient_id,
        department_id=payload.department_id,
        doctor_user_id=payload.doctor_user_id,
        service_id=payload.service_id,
        service_name=payload.service_name,
        duration_minutes=payload.duration_minutes,
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
    appt = await get_appointment(db, facility_id, appointment_id)

    if payload.appointment_date is not None:
        appt.appointment_date = payload.appointment_date
    if payload.duration_minutes is not None:
        appt.duration_minutes = payload.duration_minutes
    if payload.start_time is not None:
        appt.start_time = payload.start_time
        appt.end_time = calc_end_time(payload.start_time, appt.duration_minutes)
    if payload.doctor_user_id is not None:
        appt.doctor_user_id = payload.doctor_user_id
    if payload.status is not None:
        appt.status = payload.status
    if payload.cancellation_reason is not None:
        appt.cancellation_reason = payload.cancellation_reason
    if payload.notes is not None:
        appt.notes = payload.notes

    appt.updated_by = actor_id
    await db.flush()
    await db.refresh(appt)
    return appt


async def check_in_appointment(
    db: AsyncSession,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
    appointment_id: uuid.UUID,
    payload: AppointmentCheckInRequest,
    facility_code: str,
    facility_timezone: str,
) -> AppointmentCheckInResult:
    appt = await get_appointment(db, facility_id, appointment_id)

    # Idempotent re-entry: If already checked in with a visit, return existing visit and token
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
        )

    # Atomically create visit under HD-05 policy
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

    # Attach queue token if queue_id is provided
    token: QueueToken | None = None
    if payload.queue_id is not None:
        token = await create_token(
            db,
            queue_id=payload.queue_id,
            visit_id=visit.id,
            priority=payload.priority,
            caller_facility_id=facility_id,
        )

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
    )

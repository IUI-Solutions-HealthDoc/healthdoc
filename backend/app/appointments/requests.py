"""Patient-portal appointment requests: ask, withdraw, confirm, decline.

The patient never books a time directly. HealthDoc knows shift names, not
clinic hours, so offering slots would mean inventing them; reception, who
does know, turns a request into a real appointment with the desk's own
create path (patient, department, doctor-conflict and past-date checks).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.appointments import service
from app.appointments.models import AppointmentRequest
from app.appointments.schemas import AppointmentCreate
from app.departments.models import Department

#: How far ahead a patient may ask; further than this is a waiting list, not a booking.
MAX_DAYS_AHEAD = 60
#: Open requests per patient, so one portal account cannot flood the desk.
MAX_OPEN = 3


class RequestError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


async def bookable_departments(db: AsyncSession, facility_id: uuid.UUID) -> list[Department]:
    return list(
        (
            await db.execute(
                select(Department)
                .where(Department.facility_id == facility_id, Department.is_active.is_(True))
                .order_by(Department.name)
            )
        ).scalars()
    )


async def create_request(
    db: AsyncSession, *, facility_id: uuid.UUID, patient_id: uuid.UUID, requested_by: uuid.UUID,
    department_id: uuid.UUID, preferred_date: date, session: str, is_teleconsult: bool, reason: str | None,
    today: date,
) -> AppointmentRequest:
    if preferred_date < today or preferred_date > today + timedelta(days=MAX_DAYS_AHEAD):
        raise RequestError("date_out_of_range", f"Choose a date from today to {MAX_DAYS_AHEAD} days ahead", 422)
    department = await db.get(Department, department_id)
    if department is None or department.facility_id != facility_id or not department.is_active:
        raise RequestError("department_not_found", "Department not found", 404)
    open_count = (
        await db.execute(
            select(func.count(AppointmentRequest.id)).where(
                AppointmentRequest.patient_id == patient_id, AppointmentRequest.status == "requested"
            )
        )
    ).scalar_one()
    if open_count >= MAX_OPEN:
        raise RequestError("too_many_open_requests", f"You already have {MAX_OPEN} requests waiting for the hospital")
    request = AppointmentRequest(
        id=uuid.uuid4(), facility_id=facility_id, patient_id=patient_id, requested_by=requested_by,
        department_id=department_id, preferred_date=preferred_date, session=session,
        is_teleconsult=is_teleconsult, reason=(reason or "").strip() or None, status="requested",
    )
    db.add(request)
    await db.flush()
    return request


async def _scoped(db: AsyncSession, request_id: uuid.UUID, facility_id: uuid.UUID) -> AppointmentRequest:
    request = (
        await db.execute(
            select(AppointmentRequest)
            .where(AppointmentRequest.id == request_id, AppointmentRequest.facility_id == facility_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if request is None:
        raise RequestError("request_not_found", "Request not found", 404)
    return request


async def withdraw(
    db: AsyncSession, request_id: uuid.UUID, *, patient_id: uuid.UUID, facility_id: uuid.UUID
) -> AppointmentRequest:
    request = (
        await db.execute(
            select(AppointmentRequest)
            .where(
                AppointmentRequest.id == request_id,
                AppointmentRequest.patient_id == patient_id,
                AppointmentRequest.facility_id == facility_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if request is None:
        raise RequestError("request_not_found", "Request not found", 404)
    if request.status != "requested":
        raise RequestError("request_already_decided", f"This request is already {request.status}")
    request.status = "withdrawn"
    await db.flush()
    return request


async def confirm(
    db: AsyncSession, request_id: uuid.UUID, *, facility_id: uuid.UUID, actor_id: uuid.UUID,
    start_time: str, doctor_user_id: uuid.UUID | None, duration_minutes: int, appointment_date: date | None,
):
    request = await _scoped(db, request_id, facility_id)
    if request.status != "requested":
        raise RequestError("request_already_decided", f"This request is already {request.status}")
    appointment = await service.create_appointment(
        db, facility_id, actor_id,
        AppointmentCreate(
            patient_id=request.patient_id, department_id=request.department_id, doctor_user_id=doctor_user_id,
            duration_minutes=duration_minutes, appointment_date=appointment_date or request.preferred_date,
            start_time=start_time, is_teleconsult=request.is_teleconsult,
            notes=f"Requested online ({request.session})" + (f": {request.reason}" if request.reason else ""),
        ),
    )
    request.status, request.appointment_id, request.decided_by = "confirmed", appointment.id, actor_id
    await db.flush()
    return request, appointment


async def decline(
    db: AsyncSession, request_id: uuid.UUID, *, facility_id: uuid.UUID, actor_id: uuid.UUID, reason: str,
) -> AppointmentRequest:
    request = await _scoped(db, request_id, facility_id)
    if request.status != "requested":
        raise RequestError("request_already_decided", f"This request is already {request.status}")
    if not reason.strip():
        raise RequestError("decline_reason_required", "Tell the patient why", 422)
    request.status, request.decline_reason, request.decided_by = "declined", reason.strip(), actor_id
    await db.flush()
    return request

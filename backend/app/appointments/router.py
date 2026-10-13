"""Endpoints for appointments, service catalogue, and scheduling."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date, datetime
from typing import Iterator, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.appointments import requests, service
from app.appointments.models import AppointmentRequest
from app.appointments.schemas import (
    TIME_PATTERN,
    AppointmentCheckInRequest,
    AppointmentCheckInResult,
    AppointmentCreate,
    AppointmentOut,
    AppointmentServiceCreate,
    AppointmentServiceOut,
    AppointmentUpdate,
)
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.idempotency import (
    check_idempotency,
    hash_request_body,
    record_idempotent_response,
)
from app.departments.models import Department
from app.patients.models import Patient
from app.queue.service import require_initial_priority_allowed
from app.users.models import Facility

router = APIRouter(prefix="/appointments", tags=["appointments"])


async def _get_facility_code_and_timezone(
    db: AsyncSession, facility_id: uuid.UUID
) -> tuple[str, str]:
    result = await db.execute(
        select(Facility.code, Facility.timezone).where(Facility.id == facility_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Facility not found")
    return row.code, row.timezone


def _require_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key header is required")
    return idempotency_key


async def _replay(
    db: AsyncSession, key: str, endpoint: str, payload: BaseModel, user_id: uuid.UUID
) -> dict | None:
    cached = await check_idempotency(db, key, endpoint, hash_request_body(payload), user_id=user_id)
    return cached.response_body if cached is not None else None


@contextmanager
def _service_errors() -> Iterator[None]:
    try:
        yield
    except service.AppointmentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.AppointmentValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"code": "appointment_invalid", "message": str(exc)},
        ) from exc
    except service.AppointmentConflictError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "appointment_conflict", "message": str(exc)},
        ) from exc
    except service.AppointmentStateError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"code": exc.code, "message": str(exc)},
        ) from exc


@router.get(
    "/services",
    response_model=list[AppointmentServiceOut],
    dependencies=[Depends(require_roles("receptionist", "admin", "doctor", "nurse"))],
)
async def list_services(
    current_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
):
    """List active appointment services in the facility catalogue."""
    return await service.list_services(db, current_user.facility_id)


@router.post(
    "/services",
    response_model=AppointmentServiceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def create_service(
    payload: AppointmentServiceCreate,
    current_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Create a new service entry in the facility's scheduling catalogue."""
    key = _require_key(idempotency_key)
    endpoint = "POST /appointments/services"
    cached = await _replay(db, key, endpoint, payload, current_user.id)
    if cached is not None:
        return cached

    with _service_errors():
        svc = await service.create_service(db, current_user.facility_id, payload)
    res = AppointmentServiceOut.model_validate(svc)
    await record_idempotent_response(
        db, key, endpoint, status.HTTP_201_CREATED, res.model_dump(mode="json"), user_id=current_user.id,
    )
    await db.commit()
    return res


@router.get(
    "",
    response_model=list[AppointmentOut],
    dependencies=[Depends(require_roles("receptionist", "admin", "doctor", "nurse"))],
)
async def list_appointments(
    current_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    department_id: uuid.UUID | None = Query(None),
    doctor_user_id: uuid.UUID | None = Query(None),
    patient_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
):
    """List appointments filtered by date range, department, doctor, patient, or status."""
    return await service.list_appointments(
        db,
        current_user.facility_id,
        date_from=date_from,
        date_to=date_to,
        department_id=department_id,
        doctor_user_id=doctor_user_id,
        patient_id=patient_id,
        status=status,
    )


@router.post(
    "",
    response_model=AppointmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("receptionist", "admin", "doctor", "nurse"))],
)
async def create_appointment(
    payload: AppointmentCreate,
    current_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Book a new appointment with conflict checking and explicit teleconsult status."""
    key = _require_key(idempotency_key)
    endpoint = "POST /appointments"
    cached = await _replay(db, key, endpoint, payload, current_user.id)
    if cached is not None:
        return cached

    with _service_errors():
        appt = await service.create_appointment(
            db,
            facility_id=current_user.facility_id,
            actor_id=current_user.id,
            payload=payload,
        )
        detail = await service.get_appointment_detail(db, current_user.facility_id, appt.id)
    final_res = AppointmentOut.model_validate(detail)

    # The booking and its receipt commit together: a crash between two commits
    # left the key "in progress" forever and the desk unable to retry.
    await record_idempotent_response(
        db, key, endpoint, status.HTTP_201_CREATED, final_res.model_dump(mode="json"), user_id=current_user.id,
    )
    await db.commit()
    return final_res


# ---------------- PATIENT-PORTAL REQUESTS: the desk's side ----------------


class AppointmentRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str | None = None
    patient_uhid: str | None = None
    department_id: uuid.UUID
    department_name: str | None = None
    preferred_date: date
    session: str
    is_teleconsult: bool
    reason: str | None
    status: str
    appointment_id: uuid.UUID | None
    decline_reason: str | None
    created_at: datetime


class RequestConfirm(BaseModel):
    start_time: str = Field(..., pattern=TIME_PATTERN)
    doctor_user_id: uuid.UUID | None = None
    duration_minutes: int = Field(default=15, ge=5, le=240)
    #: Defaults to the date the patient asked for.
    appointment_date: date | None = None


class RequestDecline(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@contextmanager
def _request_errors() -> Iterator[None]:
    try:
        with _service_errors():
            yield
    except requests.RequestError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": exc.message}) from exc


@router.get(
    "/requests",
    response_model=list[AppointmentRequestOut],
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def list_appointment_requests(
    current_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    request_status: Literal["requested", "confirmed", "declined", "withdrawn"] = Query("requested", alias="status"),
) -> list[AppointmentRequestOut]:
    rows = (
        await db.execute(
            select(AppointmentRequest, Patient.full_name, Patient.uhid, Department.name)
            .join(Patient, Patient.id == AppointmentRequest.patient_id)
            .join(Department, Department.id == AppointmentRequest.department_id)
            .where(AppointmentRequest.facility_id == current_user.facility_id, AppointmentRequest.status == request_status)
            .order_by(AppointmentRequest.preferred_date, AppointmentRequest.created_at)
            .limit(200)
        )
    ).all()
    return [
        AppointmentRequestOut.model_validate(req).model_copy(
            update={"patient_name": name, "patient_uhid": uhid, "department_name": dept}
        )
        for req, name, uhid, dept in rows
    ]


@router.post(
    "/requests/{request_id}/confirm",
    response_model=AppointmentOut,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def confirm_appointment_request(
    request_id: uuid.UUID,
    payload: RequestConfirm,
    current_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = _require_key(idempotency_key)
    endpoint = f"POST /appointments/requests/{request_id}/confirm"
    cached = await _replay(db, key, endpoint, payload, current_user.id)
    if cached is not None:
        return cached
    with _request_errors():
        _request, appointment = await requests.confirm(
            db, request_id, facility_id=current_user.facility_id, actor_id=current_user.id,
            start_time=payload.start_time, doctor_user_id=payload.doctor_user_id,
            duration_minutes=payload.duration_minutes, appointment_date=payload.appointment_date,
        )
    res = AppointmentOut.model_validate(appointment)
    await record_idempotent_response(db, key, endpoint, 200, res.model_dump(mode="json"), user_id=current_user.id)
    await db.commit()
    return res


@router.post(
    "/requests/{request_id}/decline",
    response_model=AppointmentRequestOut,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def decline_appointment_request(
    request_id: uuid.UUID,
    payload: RequestDecline,
    current_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = _require_key(idempotency_key)
    endpoint = f"POST /appointments/requests/{request_id}/decline"
    cached = await _replay(db, key, endpoint, payload, current_user.id)
    if cached is not None:
        return cached
    with _request_errors():
        request = await requests.decline(
            db, request_id, facility_id=current_user.facility_id, actor_id=current_user.id, reason=payload.reason,
        )
    res = AppointmentRequestOut.model_validate(request)
    await record_idempotent_response(db, key, endpoint, 200, res.model_dump(mode="json"), user_id=current_user.id)
    await db.commit()
    return res


@router.get(
    "/{appointment_id}",
    response_model=AppointmentOut,
    dependencies=[Depends(require_roles("receptionist", "admin", "doctor", "nurse"))],
)
async def get_appointment(
    appointment_id: uuid.UUID,
    current_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
):
    """Get appointment detail."""
    with _service_errors():
        return await service.get_appointment_detail(db, current_user.facility_id, appointment_id)


@router.patch(
    "/{appointment_id}",
    response_model=AppointmentOut,
    dependencies=[Depends(require_roles("receptionist", "admin", "doctor", "nurse"))],
)
async def update_appointment(
    appointment_id: uuid.UUID,
    payload: AppointmentUpdate,
    current_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Confirm, cancel, mark no-show or reschedule an appointment."""
    key = _require_key(idempotency_key)
    endpoint = f"PATCH /appointments/{appointment_id}"
    cached = await _replay(db, key, endpoint, payload, current_user.id)
    if cached is not None:
        return cached

    with _service_errors():
        await service.update_appointment(
            db,
            facility_id=current_user.facility_id,
            actor_id=current_user.id,
            appointment_id=appointment_id,
            payload=payload,
        )
        detail = await service.get_appointment_detail(db, current_user.facility_id, appointment_id)
    res = AppointmentOut.model_validate(detail)
    await record_idempotent_response(
        db, key, endpoint, status.HTTP_200_OK, res.model_dump(mode="json"), user_id=current_user.id,
    )
    await db.commit()
    return res


@router.post(
    "/{appointment_id}/check-in",
    response_model=AppointmentCheckInResult,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def check_in_appointment(
    appointment_id: uuid.UUID,
    payload: AppointmentCheckInRequest,
    current_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Check in an appointment: creates the OPD visit and, when a queue is open, its token."""
    key = _require_key(idempotency_key)
    require_initial_priority_allowed(payload.priority, current_user.roles)
    endpoint = f"POST /appointments/{appointment_id}/check-in"
    cached = await _replay(db, key, endpoint, payload, current_user.id)
    if cached is not None:
        return cached

    facility_code, facility_tz = await _get_facility_code_and_timezone(
        db, current_user.facility_id
    )
    with _service_errors():
        result = await service.check_in_appointment(
            db,
            facility_id=current_user.facility_id,
            actor_id=current_user.id,
            appointment_id=appointment_id,
            payload=payload,
            facility_code=facility_code,
            facility_timezone=facility_tz,
        )
    await record_idempotent_response(
        db, key, endpoint, status.HTTP_200_OK, result.model_dump(mode="json"), user_id=current_user.id,
    )
    await db.commit()
    return result

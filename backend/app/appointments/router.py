"""Endpoints for appointments, service catalogue, and scheduling."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.appointments import service
from app.appointments.models import Appointment
from app.appointments.schemas import (
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
    endpoint = "POST /appointments/services"
    if idempotency_key:
        cached = await check_idempotency(
            db,
            idempotency_key,
            endpoint,
            hash_request_body(payload),
            user_id=current_user.id,
        )
        if cached is not None:
            return cached.response_body

    svc = await service.create_service(db, current_user.facility_id, payload)
    await db.commit()
    res = AppointmentServiceOut.model_validate(svc)

    if idempotency_key:
        await record_idempotent_response(
            db,
            idempotency_key,
            endpoint,
            status.HTTP_201_CREATED,
            res.model_dump(mode="json"),
            user_id=current_user.id,
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
    endpoint = "POST /appointments"
    if idempotency_key:
        cached = await check_idempotency(
            db,
            idempotency_key,
            endpoint,
            hash_request_body(payload),
            user_id=current_user.id,
        )
        if cached is not None:
            return cached.response_body

    try:
        appt = await service.create_appointment(
            db,
            facility_id=current_user.facility_id,
            actor_id=current_user.id,
            payload=payload,
        )
        await db.commit()
    except service.AppointmentConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "appointment_conflict", "message": str(exc)},
        ) from exc

    results = await service.list_appointments(
        db,
        current_user.facility_id,
        date_from=appt.appointment_date,
        date_to=appt.appointment_date,
        patient_id=appt.patient_id,
    )
    final_res = None
    for res in results:
        if res["id"] == appt.id:
            final_res = AppointmentOut.model_validate(res)
            break
    if final_res is None:
        final_res = AppointmentOut.model_validate(appt)

    if idempotency_key:
        await record_idempotent_response(
            db,
            idempotency_key,
            endpoint,
            status.HTTP_201_CREATED,
            final_res.model_dump(mode="json"),
            user_id=current_user.id,
        )
        await db.commit()

    return final_res


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
    try:
        appt = await service.get_appointment(db, current_user.facility_id, appointment_id)
    except service.AppointmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    results = await service.list_appointments(
        db,
        current_user.facility_id,
        date_from=appt.appointment_date,
        date_to=appt.appointment_date,
        patient_id=appt.patient_id,
    )
    for res in results:
        if res["id"] == appt.id:
            return res
    return appt


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
):
    """Update or reschedule or cancel an appointment."""
    try:
        appt = await service.update_appointment(
            db,
            facility_id=current_user.facility_id,
            actor_id=current_user.id,
            appointment_id=appointment_id,
            payload=payload,
        )
        await db.commit()
    except service.AppointmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    results = await service.list_appointments(
        db,
        current_user.facility_id,
        date_from=appt.appointment_date,
        date_to=appt.appointment_date,
        patient_id=appt.patient_id,
    )
    for res in results:
        if res["id"] == appt.id:
            return res
    return appt


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
    """Check in an appointment: atomically creates OPD visit and queue token under HD-05 policy."""
    endpoint = f"POST /appointments/{appointment_id}/check-in"
    if idempotency_key:
        cached = await check_idempotency(
            db,
            idempotency_key,
            endpoint,
            hash_request_body(payload),
            user_id=current_user.id,
        )
        if cached is not None:
            return cached.response_body

    facility_code, facility_tz = await _get_facility_code_and_timezone(
        db, current_user.facility_id
    )
    try:
        result = await service.check_in_appointment(
            db,
            facility_id=current_user.facility_id,
            actor_id=current_user.id,
            appointment_id=appointment_id,
            payload=payload,
            facility_code=facility_code,
            facility_timezone=facility_tz,
        )
        await db.commit()

        if idempotency_key:
            await record_idempotent_response(
                db,
                idempotency_key,
                endpoint,
                status.HTTP_200_OK,
                result.model_dump(mode="json"),
                user_id=current_user.id,
            )
            await db.commit()
        return result
    except service.AppointmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

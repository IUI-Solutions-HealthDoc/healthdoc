"""Immunization router (HD-29)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, CurrentUser, DbSession, require_roles
from app.immunization import service
from app.immunization.schemas import (
    ImmunizationCertificateOut,
    ImmunizationRecordCreate,
    ImmunizationRecordOut,
    PatientImmunizationScheduleOut,
    VaccineOut,
)

router = APIRouter(prefix="/immunization", tags=["immunization"])


@router.get(
    "/catalogue",
    response_model=list[VaccineOut],
    dependencies=[Depends(require_roles("nurse", "doctor", "admin", "superadmin", "receptionist", "registration"))],
)
async def list_catalogue(db: DbSession) -> list[VaccineOut]:
    """Retrieve standardized national/facility vaccine catalogue."""
    catalogue = await service.get_catalogue(db)
    return [VaccineOut.model_validate(v) for v in catalogue]


@router.get(
    "/patients/{patient_id}",
    response_model=PatientImmunizationScheduleOut,
    dependencies=[Depends(require_roles("nurse", "doctor", "admin", "superadmin", "receptionist", "registration", "patient"))],
)
async def get_patient_immunization_schedule(
    patient_id: uuid.UUID,
    db: DbSession,
) -> PatientImmunizationScheduleOut:
    """Retrieve patient administered records and upcoming/due immunization schedule."""
    try:
        return await service.get_patient_schedule(db, patient_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/records",
    response_model=ImmunizationRecordOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("nurse", "doctor", "admin", "superadmin"))],
)
async def record_immunization(
    payload: ImmunizationRecordCreate,
    db_user: CurrentDbUser,
    db: DbSession,
) -> ImmunizationRecordOut:
    """Record a vaccine administration event with batch number and expiry traceability."""
    try:
        return await service.record_administration(db, payload, db_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/patients/{patient_id}/certificate",
    response_model=ImmunizationCertificateOut,
    dependencies=[Depends(require_roles("nurse", "doctor", "admin", "superadmin", "receptionist", "registration", "patient"))],
)
async def get_immunization_certificate(
    patient_id: uuid.UUID,
    db_user: CurrentDbUser,
    db: DbSession,
) -> ImmunizationCertificateOut:
    """Generate official printable immunization certificate for a patient."""
    try:
        return await service.generate_certificate(db, patient_id, db_user.facility_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

"""Immunization router (HD-29)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, CurrentUser, DbSession, require_roles
from app.immunization import service
from app.common.clinical_write import ClinicalWriteKey, clinical_write
from app.common.patient_scope import require_patient_access
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
    dependencies=[Depends(require_roles("nurse", "doctor", "admin", "receptionist", "registration"))],
)
async def list_catalogue(db: DbSession) -> list[VaccineOut]:
    """Retrieve standardized national/facility vaccine catalogue."""
    catalogue = await service.get_catalogue(db)
    return [VaccineOut.model_validate(v) for v in catalogue]


@router.get(
    "/patients/{patient_id}",
    response_model=PatientImmunizationScheduleOut,
    dependencies=[Depends(require_roles("nurse", "doctor", "admin", "receptionist", "registration", "patient"))],
)
async def get_patient_immunization_schedule(
    patient_id: uuid.UUID,
    current_user: CurrentDbUser,
    db: DbSession,
) -> PatientImmunizationScheduleOut:
    """Retrieve patient administered records and upcoming/due immunization schedule."""
    await require_patient_access(db, patient_id, current_user)
    try:
        return await service.get_patient_schedule(db, patient_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/records",
    response_model=ImmunizationRecordOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("nurse", "doctor", "admin"))],
)
async def record_immunization(
    payload: ImmunizationRecordCreate,
    current_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: ClinicalWriteKey,
) -> ImmunizationRecordOut:
    """Record a vaccine administration event with batch number and expiry traceability."""
    await require_patient_access(db, payload.patient_id, current_user)
    try:
        return await clinical_write(db, idempotency_key, "POST /immunization/records", payload,
            current_user, ImmunizationRecordOut,
            lambda: service.record_administration(db, payload, current_user.id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/patients/{patient_id}/certificate",
    response_model=ImmunizationCertificateOut,
    dependencies=[Depends(require_roles("nurse", "doctor", "admin", "receptionist", "registration", "patient"))],
)
async def get_immunization_certificate(
    patient_id: uuid.UUID,
    current_user: CurrentDbUser,
    db: DbSession,
) -> ImmunizationCertificateOut:
    """Generate official printable immunization certificate for a patient."""
    await require_patient_access(db, patient_id, current_user)
    try:
        return await service.generate_certificate(db, patient_id, current_user.facility_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.auth.deps import CurrentUser, require_roles
from app.admissions import schemas, service

router = APIRouter(prefix="/admissions", tags=["admissions"])


@router.post("", response_model=schemas.AdmissionOut, dependencies=[Depends(require_roles("doctor", "nurse", "admin"))])
async def create_admission(
    payload: schemas.AdmissionCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    return await service.admit_patient(db, payload, user)


@router.post("/{admission_id}/transfer", response_model=schemas.TransferOut, dependencies=[Depends(require_roles("doctor", "nurse", "admin"))])
async def transfer_admission(
    admission_id: uuid.UUID,
    payload: schemas.TransferCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    return await service.transfer_patient(db, admission_id, payload, user)


@router.post("/{admission_id}/discharge", response_model=schemas.DischargeOut, dependencies=[Depends(require_roles("doctor", "admin"))])
async def discharge_admission(
    admission_id: uuid.UUID,
    payload: schemas.DischargeCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    return await service.discharge_patient(db, admission_id, payload, user)
"""Blood bank module router (HD-29)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, DbSession, require_roles
from app.blood_bank import service
from app.blood_bank.schemas import (
    BloodCrossmatchCreate,
    BloodCrossmatchOut,
    BloodDonorCreate,
    BloodDonorOut,
    BloodIssueRequest,
    BloodUnitCreate,
    BloodUnitOut,
)

router = APIRouter(prefix="/blood-bank", tags=["blood_bank"])


@router.get(
    "/donors",
    response_model=list[BloodDonorOut],
    dependencies=[Depends(require_roles("lab_tech", "pathologist", "nurse", "doctor", "admin"))],
)
async def list_blood_donors(
    db: DbSession,
    blood_group: str | None = Query(default=None),
    is_eligible: bool | None = Query(default=None),
) -> list[BloodDonorOut]:
    """List blood donors with optional filter by blood group and eligibility."""
    donors = await service.list_donors(db, blood_group=blood_group, is_eligible=is_eligible)
    return [BloodDonorOut.model_validate(d) for d in donors]


@router.post(
    "/donors",
    response_model=BloodDonorOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("lab_tech", "pathologist", "admin"))],
)
async def register_blood_donor(
    payload: BloodDonorCreate,
    current_user: CurrentDbUser,
    db: DbSession,
) -> BloodDonorOut:
    """Register and screen a voluntary or replacement blood donor."""
    return await service.create_donor(db, payload, current_user.id)


@router.get(
    "/units",
    response_model=list[BloodUnitOut],
    dependencies=[Depends(require_roles("lab_tech", "pathologist", "nurse", "doctor", "admin"))],
)
async def list_blood_units(
    db: DbSession,
    unit_status: str | None = Query(default=None, alias="status"),
    blood_group: str | None = Query(default=None),
    screening_status: str | None = Query(default=None),
) -> list[BloodUnitOut]:
    """List blood units with status and blood group filtering."""
    units = await service.list_units(
        db, status=unit_status, blood_group=blood_group, screening_status=screening_status
    )
    return [BloodUnitOut.model_validate(u) for u in units]


@router.post(
    "/units",
    response_model=BloodUnitOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("lab_tech", "pathologist", "admin"))],
)
async def add_blood_unit(
    payload: BloodUnitCreate,
    db: DbSession,
) -> BloodUnitOut:
    """Add a newly collected and screened blood unit to inventory."""
    try:
        return await service.create_unit(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/crossmatch",
    response_model=BloodCrossmatchOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("lab_tech", "pathologist", "doctor", "admin"))],
)
async def register_blood_crossmatch(
    payload: BloodCrossmatchCreate,
    current_user: CurrentDbUser,
    db: DbSession,
) -> BloodCrossmatchOut:
    """Perform and record major/minor crossmatch compatibility test for patient."""
    try:
        return await service.create_crossmatch(db, payload, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/issue",
    response_model=BloodCrossmatchOut,
    dependencies=[Depends(require_roles("lab_tech", "pathologist", "nurse", "doctor", "admin"))],
)
async def issue_blood_unit(
    payload: BloodIssueRequest,
    current_user: CurrentDbUser,
    db: DbSession,
) -> BloodCrossmatchOut:
    """Issue a compatible crossmatched blood unit to a patient for transfusion."""
    try:
        return await service.issue_blood(db, payload, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

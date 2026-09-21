"""Blood bank module router (HD-29)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.auth.deps import CurrentDbUser, DbSession, require_roles
from app.blood_bank import service
from app.blood_bank.models import BloodDonor, BloodUnit, BloodCrossmatch
from app.common.clinical_write import ClinicalWriteKey, clinical_write
from app.common.patient_scope import require_patient_access
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


async def _donor_access(db, donor_id, actor):
    donor = (await db.execute(select(BloodDonor).where(
        BloodDonor.id == donor_id, BloodDonor.id.in_(service.donor_scope(actor.facility_id)),
    ))).scalar_one_or_none()
    if donor is None:
        raise HTTPException(404, "Donor not found")
    if donor.patient_id:
        await require_patient_access(db, donor.patient_id, actor)


async def _unit_access(db, unit_id, actor):
    unit = (await db.execute(select(BloodUnit).where(
        BloodUnit.id == unit_id, BloodUnit.donor_id.in_(service.donor_scope(actor.facility_id)),
    ))).scalar_one_or_none()
    if unit is None:
        raise HTTPException(404, "Blood unit not found")
    await _donor_access(db, unit.donor_id, actor)


@router.get(
    "/donors",
    response_model=list[BloodDonorOut],
    dependencies=[Depends(require_roles("lab_tech", "pathologist", "nurse", "doctor", "admin"))],
)
async def list_blood_donors(
    db: DbSession,
    current_user: CurrentDbUser,
    blood_group: str | None = Query(default=None),
    is_eligible: bool | None = Query(default=None),
) -> list[BloodDonorOut]:
    """List blood donors with optional filter by blood group and eligibility."""
    donors = await service.list_donors(db, current_user.facility_id, blood_group=blood_group, is_eligible=is_eligible)
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
    idempotency_key: ClinicalWriteKey,
) -> BloodDonorOut:
    """Register and screen a voluntary or replacement blood donor."""
    if payload.patient_id:
        await require_patient_access(db, payload.patient_id, current_user)
    return await clinical_write(db, idempotency_key, "POST /blood-bank/donors", payload,
        current_user, BloodDonorOut, lambda: service.create_donor(db, payload, current_user.id))


@router.get(
    "/units",
    response_model=list[BloodUnitOut],
    dependencies=[Depends(require_roles("lab_tech", "pathologist", "nurse", "doctor", "admin"))],
)
async def list_blood_units(
    db: DbSession,
    current_user: CurrentDbUser,
    unit_status: str | None = Query(default=None, alias="status"),
    blood_group: str | None = Query(default=None),
    screening_status: str | None = Query(default=None),
) -> list[BloodUnitOut]:
    """List blood units with status and blood group filtering."""
    units = await service.list_units(
        db, current_user.facility_id, status=unit_status, blood_group=blood_group, screening_status=screening_status
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
    current_user: CurrentDbUser,
    idempotency_key: ClinicalWriteKey,
) -> BloodUnitOut:
    """Add a newly collected and screened blood unit to inventory."""
    await _donor_access(db, payload.donor_id, current_user)
    try:
        return await clinical_write(db, idempotency_key, "POST /blood-bank/units", payload,
            current_user, BloodUnitOut, lambda: service.create_unit(db, payload, current_user.id))
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
    idempotency_key: ClinicalWriteKey,
) -> BloodCrossmatchOut:
    """Perform and record major/minor crossmatch compatibility test for patient."""
    await require_patient_access(db, payload.patient_id, current_user)
    await _unit_access(db, payload.unit_id, current_user)
    try:
        return await clinical_write(db, idempotency_key, "POST /blood-bank/crossmatch", payload,
            current_user, BloodCrossmatchOut, lambda: service.create_crossmatch(db, payload, current_user.id))
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
    idempotency_key: ClinicalWriteKey,
) -> BloodCrossmatchOut:
    """Issue a compatible crossmatched blood unit to a patient for transfusion."""
    crossmatch = (await db.execute(select(BloodCrossmatch).join(BloodUnit).where(
        BloodCrossmatch.id == payload.crossmatch_id,
        BloodUnit.donor_id.in_(service.donor_scope(current_user.facility_id)),
    ))).scalar_one_or_none()
    if crossmatch is None:
        raise HTTPException(404, "Crossmatch record not found")
    await require_patient_access(db, crossmatch.patient_id, current_user)
    await _unit_access(db, crossmatch.unit_id, current_user)
    try:
        return await clinical_write(db, idempotency_key, "POST /blood-bank/issue", payload,
            current_user, BloodCrossmatchOut, lambda: service.issue_blood(db, payload, current_user.id), status=200)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

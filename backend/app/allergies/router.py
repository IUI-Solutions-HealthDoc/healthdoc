"""backend/app/allergies/router.py -- /allergies endpoints (#286, schema v3.14 §3 0032).

The server-side prescribing gate already existed in service.check_prescription_item and
runs on every prescription save. What was missing was any way to populate or read the
register over the API — until now the only way in was direct SQL, which meant the gate
had nothing to check against in practice.

There is deliberately **no DELETE**. Allergy records are corrected via status
(`refuted`, `entered_in_error`, `inactive`), never removed: a deleted allergy that was
real is precisely the failure mode 0032's status enum exists to prevent.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.allergies import service
from app.allergies.schemas import AllergyCreate, AllergyOut, AllergyStatusUpdate
from app.allergies.service import AllergyVersionConflict
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db

router = APIRouter(prefix="/allergies", tags=["allergies"])


@router.get(
    "/patients/{patient_id}",
    response_model=list[AllergyOut],
    dependencies=[Depends(require_roles("doctor", "nurse", "pharmacist", "receptionist", "admin"))],
)
async def list_patient_allergies(
    patient_id: UUID,
    current_db_user: CurrentDbUser,
    include_inactive: bool = Query(
        default=False,
        description="Include refuted / entered_in_error / inactive entries. The "
                    "prescribing banner wants active only; the review screen wants all.",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[AllergyOut]:
    rows = await service.list_allergies(db, patient_id, include_inactive=include_inactive)
    return [AllergyOut.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=AllergyOut,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("doctor", "nurse", "admin"))],
)
async def create_allergy(
    payload: AllergyCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> AllergyOut:
    allergy = await service.record_allergy(db, payload, recorded_by=current_db_user.id)
    return AllergyOut.model_validate(allergy)


@router.patch(
    "/{allergy_id}/status",
    response_model=AllergyOut,
    dependencies=[Depends(require_roles("doctor", "admin"))],
)
async def update_allergy_status(
    allergy_id: UUID,
    payload: AllergyStatusUpdate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> AllergyOut:
    try:
        allergy = await service.set_status(
            db,
            allergy_id,
            status=payload.status,
            row_version=payload.row_version,
            updated_by=current_db_user.id,
        )
    except AllergyVersionConflict as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={"code": "row_version_conflict", "message": str(exc)},
        ) from exc
    if allergy is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="allergy_not_found"
        )
    return AllergyOut.model_validate(allergy)


@router.post(
    "/{allergy_id}/verify",
    response_model=AllergyOut,
    dependencies=[Depends(require_roles("doctor", "admin"))],
)
async def verify_allergy(
    allergy_id: UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> AllergyOut:
    """Clinician confirmation of a reported allergy.

    Restricted to doctors: a nurse or receptionist can record what an attendant
    reports, but verification is a clinical judgement and is what downstream
    reviewers will read as such.
    """
    allergy = await service.verify_allergy(db, allergy_id, verified_by=current_db_user.id)
    if allergy is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="allergy_not_found"
        )
    return AllergyOut.model_validate(allergy)

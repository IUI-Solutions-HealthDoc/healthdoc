import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.auth.deps import CurrentUser, require_roles
from app.opd.models import Vitals
from app.users.models import User
from app.encounters.vitals_schemas import VitalsCreate, VitalsOut

router = APIRouter(prefix="/encounters", tags=["vitals"])


async def _resolve_user(db: AsyncSession, keycloak_sub: str) -> User:
    """JWT sub -> users row. Same pattern as app/admissions/service.py."""
    result = await db.execute(select(User).where(User.keycloak_sub == keycloak_sub))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not provisioned")
    return user


def _compute_bmi(height_cm, weight_kg):
    if not height_cm or not weight_kg:
        return None
    height_m = height_cm / 100
    return round(weight_kg / (height_m * height_m), 1)


def _compute_whr(waist_cm, hip_cm):
    if not waist_cm or not hip_cm:
        return None
    return round(waist_cm / hip_cm, 2)


@router.post(
    "/{encounter_id}/vitals",
    response_model=VitalsOut,
    status_code=201,
    dependencies=[Depends(require_roles("doctor", "nurse"))],
)
async def record_vitals(
    encounter_id: uuid.UUID,
    payload: VitalsCreate,
    auth_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    user = await _resolve_user(db, auth_user.sub)

    data = payload.model_dump(exclude={"encounter_id"})
    vitals = Vitals(
        **data,
        encounter_id=encounter_id,
        bmi=_compute_bmi(payload.height_cm, payload.weight_kg),
        whr=_compute_whr(payload.waist_cm, payload.hip_cm),
        created_by=user.id,
    )
    db.add(vitals)
    await db.flush()
    await db.refresh(vitals)
    return vitals


@router.get("/{encounter_id}/vitals", response_model=list[VitalsOut])
async def list_vitals(encounter_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Vitals)
        .where(Vitals.encounter_id == encounter_id)
        .order_by(Vitals.measured_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()

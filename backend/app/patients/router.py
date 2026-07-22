"""patients module router — B2-W1-02: registration endpoint."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, require_roles
from app.common.db import get_db
from app.patients.models import Patient
from app.patients.schemas import PatientCreate, PatientOut
from app.patients.service import generate_uhid
from app.users.models import Facility, User

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("/ping")
async def ping() -> dict:
    return {"module": "patients", "status": "stub"}


@router.post(
    "",
    status_code=201,
    response_model=PatientOut,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def register_patient(
    payload: PatientCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Patient:
    facility = await db.get(Facility, payload.facility_id)
    if not facility:
        raise HTTPException(404, "Facility not found")

    # Resolve the JWT subject to the app-side users row. No shared helper
    # exists for this yet (see app/common/modules.py:47 for the same pattern
    # done inline) — worth promoting to app/auth/deps.py as get_current_db_user()
    # once more than one module needs it.
    db_user = (
        await db.execute(select(User).where(User.keycloak_sub == current_user.sub))
    ).scalar_one_or_none()
    if not db_user:
        raise HTTPException(403, "No user profile found for this account")

    uhid = await generate_uhid(db, state_code=facility.state_code, facility_code=facility.code)

    patient = Patient(
        uhid=uhid,
        full_name=payload.full_name,
        sex=payload.sex,
        dob=payload.dob,
        age_years=payload.age_years,
        mobile=payload.mobile,
        abha_number=payload.abha_number,
        facility_id=payload.facility_id,
        identity_path="demographics_only",  # ABHA/Aadhaar identity paths land in a later ticket
        identity_status="verified",
        created_by=db_user.id,
    )
    db.add(patient)
    await db.flush()
    await db.refresh(patient)
    return patient
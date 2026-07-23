"""patients module router — B2-W1-02: registration endpoint."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.patients.models import Patient
from app.patients.schemas import PatientCreate, PatientOut
from app.patients.service import generate_uhid
from app.users.models import Facility

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
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> Patient:
    facility = await db.get(Facility, payload.facility_id)
    if not facility:
        raise HTTPException(404, "Facility not found")

    uhid = await generate_uhid(db, state_code=facility.state_code, facility_code=facility.code)

    # NOTE: identity_path is hardcoded to demographics_only, and no rows are
    # written to patient_identifiers or photo_file_id here. ABDM/Aadhaar/THID
    # identity paths are out of scope for this ticket — tracked as B2-W2-01.
    patient = Patient(
        uhid=uhid,
        full_name=payload.full_name,
        sex=payload.sex,
        dob=payload.dob,
        age_years=payload.age_years,
        mobile=payload.mobile,
        abha_number=payload.abha_number,
        facility_id=payload.facility_id,
        identity_path="demographics_only",
        identity_status="verified",
        created_by=current_db_user.id,
    )
    db.add(patient)
    await db.flush()
    await db.refresh(patient)
    return patient
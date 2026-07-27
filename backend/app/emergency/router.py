"""emergency module router — THID issuance for unidentified/emergency patients."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.emergency.schemas import EmergencyPatientCreate, EmergencyPatientOut
from app.emergency.service import generate_thid
from app.patients.models import Patient
from app.users.models import Facility

router = APIRouter(prefix="/emergency", tags=["emergency"])


@router.get("/ping")
async def ping() -> dict:
    return {"module": "emergency", "status": "stub"}


@router.post(
    "/register",
    status_code=201,
    response_model=EmergencyPatientOut,
    dependencies=[Depends(require_roles("receptionist", "admin", "nurse"))],
    # role list is a guess — confirm who's actually meant to trigger emergency
    # registration (likely whoever's at the ED desk, may include doctors/nurses
    # directly rather than only receptionist/admin)
)
async def register_emergency_patient(
    payload: EmergencyPatientCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> Patient:
    facility = await db.get(Facility, payload.facility_id)
    if not facility:
        raise HTTPException(404, "Facility not found")

    thid = await generate_thid(db, facility_code=facility.code)

    patient = Patient(
        thid=thid,
        full_name=payload.full_name or f"Unknown ({thid})",
        sex=payload.sex,
        age_years=payload.age_years,
        mobile=payload.mobile,
        facility_id=payload.facility_id,
        identity_path="thid",
        identity_status="identity_unverified",
        created_by=current_db_user.id,
    )
    db.add(patient)
    await db.flush()
    await db.refresh(patient)
    return patient

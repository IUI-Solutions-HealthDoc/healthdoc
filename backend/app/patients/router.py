"""patients module router — B2-W1-02: registration endpoint."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.patients.models import Patient
from app.patients.schemas import (
    PatientCreate, PatientOut,
    PatientSearchRequest, PatientSearchResponse, PatientSearchResult,)
from app.patients.service import generate_uhid, build_aadhaar_identifier, search_patients, mask_mobile
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

    if payload.aadhaar_number:
        identity_path = "aadhaar_mobile"
        identity_status = "identity_unverified"
    else:
        identity_path = "demographics_only"
        identity_status = "identity_unverified"

    patient = Patient(
        uhid=uhid,
        full_name=payload.full_name,
        sex=payload.sex,
        dob=payload.dob,
        age_years=payload.age_years,
        mobile=payload.mobile,
        abha_number=payload.abha_number,
        facility_id=payload.facility_id,
        identity_path=identity_path,
        identity_status=identity_status,
        created_by=current_db_user.id,
    )
    db.add(patient)
    await db.flush()

    if payload.aadhaar_number:
        db.add(build_aadhaar_identifier(
            patient_id=patient.id,
            aadhaar_number=payload.aadhaar_number,
            captured_by=current_db_user.id,
        ))
        await db.flush()

    await db.refresh(patient)
    return patient

@router.post(
    "/search",
    response_model=PatientSearchResponse,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def search_patients_endpoint(
    payload: PatientSearchRequest,
    db: AsyncSession = Depends(get_db),
) -> PatientSearchResponse:
    results, total = await search_patients(
        db,
        full_name=payload.full_name,
        dob=payload.dob,
        mobile=payload.mobile,
        uhid=payload.uhid,
        aadhaar_number=payload.aadhaar_number,
        abha_number=payload.abha_number,
        facility_id=payload.facility_id,
        page=payload.page,
        page_size=payload.page_size,
    )
    items = [
        PatientSearchResult(
            id=patient.id,
            uhid=patient.uhid,
            full_name=patient.full_name,
            sex=patient.sex,
            age_years=patient.age_years,
            mobile_masked=mask_mobile(patient.mobile),
            match_score=round(score, 3),
            matched_on=matched_on,
        )
        for patient, score, matched_on in results
    ]
    return PatientSearchResponse(items=items, page=payload.page, page_size=payload.page_size, total=total)
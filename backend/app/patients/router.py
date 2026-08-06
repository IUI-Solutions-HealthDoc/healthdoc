"""patients module router — B2-W1-02: registration endpoint."""
import uuid
from fastapi import APIRouter, Depends, HTTPException ,Header
from typing import Annotated
import hashlib, json

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.patients.models import Patient
from app.patients.schemas import (
    PatientCreate, PatientOut,
    PatientUpdate,
    PatientSearchRequest, PatientSearchResponse, PatientSearchResult,)
from app.audit.context import AuditActor
from app.audit.deps import get_current_actor_dependency
from app.patients.service import generate_uhid, build_aadhaar_identifier, search_patients, mask_mobile, update_patient
from app.users.models import Facility

router = APIRouter(prefix="/patients", tags=["patients"])

async def idempotency_guard(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: AsyncSession = Depends(get_db),
) -> str:
    if not idempotency_key:
        raise HTTPException(400, {"code": "missing_idempotency_key",
            "message": "Idempotency-Key header is required for this endpoint"})
    return idempotency_key


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
    idempotency_key: str = Depends(idempotency_guard),  
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


@router.patch(
    "/{patient_id}",
    response_model=PatientOut,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def update_patient_endpoint(
    patient_id: uuid.UUID,
    payload: PatientUpdate,
    current_db_user: CurrentDbUser,
    # get_current_actor_dependency resolves JWT sub -> users.id and stores
    # the actor in request-scoped context so write_audit_log() picks it up
    # automatically (ip_address, user_id, role) — no need to thread them
    # through the service call by hand.
    actor: AuditActor = Depends(get_current_actor_dependency),
    db: AsyncSession = Depends(get_db),
) -> Patient:
    try:
        return await update_patient(
            db,
            patient_id=patient_id,
            facility_id=current_db_user.facility_id,
            payload=payload,
            updated_by=current_db_user.id,
            reason=payload.reason,
        )
    except ValueError as e:
        code = str(e)
        if code == "patient_not_found":
            raise HTTPException(404, {"code": "patient_not_found"})
        if code == "cannot_update_merged_patient":
            raise HTTPException(409, {"code": "cannot_update_merged_patient"})
        raise HTTPException(400, str(e))


from app.patients.schemas import MergeRequestCreate, MergeActionRequest, MergeLogOut
from app.patients.service import request_merge, approve_merge, reject_merge


@router.post(
    "/merge",
    status_code=201,
    response_model=MergeLogOut,
    dependencies=[Depends(require_roles("admin", "supervisor"))],
)
async def request_patient_merge(
    payload: MergeRequestCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> MergeLogOut:
    try:
        merge_log = await request_merge(
            db,
            source_patient_id=payload.source_patient_id,
            target_patient_id=payload.target_patient_id,
            source_type=payload.source_type,
            reason=payload.reason,
            requested_by=current_db_user.id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return merge_log


@router.post(
    "/merge/{merge_id}/approve",
    response_model=MergeLogOut,
    dependencies=[Depends(require_roles("admin", "supervisor"))],
)
async def approve_patient_merge(
    merge_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> MergeLogOut:
    try:
        merge_log = await approve_merge(db, merge_log_id=merge_id, approved_by=current_db_user.id)
    except ValueError as e:
        if str(e) == "self_approval_not_allowed":
            raise HTTPException(409, {"code": "self_approval_not_allowed"})
        raise HTTPException(400, str(e))
    return merge_log


@router.post(
    "/merge/{merge_id}/reject",
    response_model=MergeLogOut,
    dependencies=[Depends(require_roles("admin", "supervisor"))],
)
async def reject_patient_merge(
    merge_id: uuid.UUID,
    payload: MergeActionRequest,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> MergeLogOut:
    try:
        merge_log = await reject_merge(db, merge_log_id=merge_id, rejected_by=current_db_user.id, reason=payload.reason)
    except ValueError as e:
        if str(e) == "self_approval_not_allowed":
            raise HTTPException(409, {"code": "self_approval_not_allowed"})
        raise HTTPException(400, str(e))
    return merge_log

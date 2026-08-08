"""patients module router — registration, search, update, merge endpoints."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditActor
from app.audit.deps import get_current_actor_dependency
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.idempotency import (
    check_idempotency, hash_request_body, record_idempotent_response,
)
from app.patients.models import Patient
from app.patients.schemas import (
    MergeActionRequest, MergeLogOut, MergeRequestCreate,
    PatientCreate, PatientOut,
    PatientSearchRequest, PatientSearchResponse, PatientSearchResult,
    PatientUpdate,
)
from app.patients.service import (
    approve_merge, build_aadhaar_identifier, find_duplicate_by_aadhaar,
    generate_uhid, mask_mobile, reject_merge, request_merge,
    search_patients, update_patient,
)
from app.users.models import Facility

router = APIRouter(prefix="/patients", tags=["patients"])

_REGISTER_ENDPOINT = "POST /patients"


async def _require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if not idempotency_key:
        raise HTTPException(400, {"code": "missing_idempotency_key",
            "message": "Idempotency-Key header is required for this endpoint"})
    return idempotency_key


@router.get("/ping")
async def ping() -> dict:
    return {"module": "patients", "status": "ok"}


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
    idempotency_key: str = Depends(_require_idempotency_key),
) -> Patient:
    """Register a new patient.

    facility_id comes from the authenticated user's token — never from the
    request body (B3 fix: a receptionist at facility A must not be able to
    register patients into facility B).

    Idempotency-Key header required: a network retry with the same key
    returns the original patient instead of creating a duplicate (real
    reserve-then-store, not just header presence check).
    """
    # Real idempotency: reserve the key before doing any work, replay if seen
    request_hash = hash_request_body(payload)
    existing = await check_idempotency(
        db, idempotency_key, _REGISTER_ENDPOINT, request_hash,
        user_id=current_db_user.id,
    )
    if existing is not None:
        return existing.response_body  # replay stored response

    facility = await db.get(Facility, current_db_user.facility_id)
    if not facility:
        raise HTTPException(404, "Facility not found")

    # B8: duplicate Aadhaar check before insert
    if payload.aadhaar_number:
        duplicate = await find_duplicate_by_aadhaar(
            db,
            aadhaar_number=payload.aadhaar_number,
            facility_id=current_db_user.facility_id,
        )
        if duplicate:
            raise HTTPException(409, {
                "code": "duplicate_aadhaar",
                "candidate_patient_id": str(duplicate.id),
                "message": "A patient with this Aadhaar number already exists",
            })

    # TZ fix: derive year from facility's local timezone, not UTC
    uhid = await generate_uhid(
        db,
        state_code=facility.state_code,
        facility_code=facility.code,
        facility_timezone=facility.timezone,
    )

    if payload.aadhaar_number:
        identity_path = "aadhaar_mobile"
    else:
        identity_path = "demographics_only"

    patient = Patient(
        uhid=uhid,
        full_name=payload.full_name,
        sex=payload.sex,
        dob=payload.dob,
        age_years=payload.age_years,
        mobile=payload.mobile,
        abha_number=payload.abha_number,
        facility_id=current_db_user.facility_id,  # B3: from token, not payload
        identity_path=identity_path,
        identity_status="identity_unverified",
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

    # Store response so retries replay it without re-running registration
    response = PatientOut.model_validate(patient).model_dump(mode="json")
    # user_id is REQUIRED here, not optional. check_idempotency() above reads
    # with user_id=current_db_user.id, and the uniqueness key is
    # (key, user_id, endpoint) per 0003a — so recording without it stores NULL,
    # the replay lookup never matches, and idempotency silently does nothing:
    # a retried registration creates a second patient. Failing open is worse
    # than failing loud here.
    await record_idempotent_response(
        db, idempotency_key, _REGISTER_ENDPOINT, 201, response,
        user_id=current_db_user.id,
    )

    return patient


@router.post(
    "/search",
    response_model=PatientSearchResponse,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def search_patients_endpoint(
    payload: PatientSearchRequest,
    current_db_user: CurrentDbUser,  # B4: facility_id from token
    db: AsyncSession = Depends(get_db),
) -> PatientSearchResponse:
    """Search patients within the caller's facility only.

    facility_id is always sourced from current_db_user — never from the
    request body (B4 fix: cross-facility search is consent-gated, not a
    default behaviour any receptionist can trigger by supplying a UUID).
    """
    results, total = await search_patients(
        db,
        full_name=payload.full_name,
        dob=payload.dob,
        mobile=payload.mobile,
        uhid=payload.uhid,
        aadhaar_number=payload.aadhaar_number,
        abha_number=payload.abha_number,
        facility_id=current_db_user.facility_id,  # B4: unconditional, from token
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
    return PatientSearchResponse(
        items=items, page=payload.page, page_size=payload.page_size, total=total,
    )


@router.patch(
    "/{patient_id}",
    response_model=PatientOut,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def update_patient_endpoint(
    patient_id: uuid.UUID,
    payload: PatientUpdate,
    current_db_user: CurrentDbUser,
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
        return await request_merge(
            db,
            source_patient_id=payload.source_patient_id,
            target_patient_id=payload.target_patient_id,
            source_type=payload.source_type,
            reason=payload.reason,
            requested_by=current_db_user.id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


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
        return await approve_merge(db, merge_log_id=merge_id, approved_by=current_db_user.id)
    except ValueError as e:
        if str(e) == "self_approval_not_allowed":
            raise HTTPException(409, {"code": "self_approval_not_allowed"})
        raise HTTPException(400, str(e))


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
        return await reject_merge(
            db, merge_log_id=merge_id,
            rejected_by=current_db_user.id, reason=payload.reason,
        )
    except ValueError as e:
        if str(e) == "self_approval_not_allowed":
            raise HTTPException(409, {"code": "self_approval_not_allowed"})
        raise HTTPException(400, str(e))

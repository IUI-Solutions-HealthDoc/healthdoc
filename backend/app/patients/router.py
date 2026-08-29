"""patients module router — registration, search, update, merge endpoints."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.audit.context import AuditActor
from app.audit.deps import get_current_actor_dependency
from app.audit.service import write_audit_log
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.idempotency import (
    check_idempotency, hash_request_body, record_idempotent_response,
)
from app.patients.models import Patient
from app.patients.schemas import (
    MergeActionRequest, MergeLogOut, MergeRequestCreate,
    PatientCreate, PatientDetailOut, PatientOut,
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

    # DPDP data-access logging (#290). Creating a patient record is the first
    # time this person's data exists in the system and it was leaving no audit
    # row at all: Patient has no __audit_resource_type__, so listeners.py never
    # sees it, and the only audited_mutation() calls in patients/service.py are
    # on update/merge. Proven against the running stack rather than inferred —
    # six patients in the dev database, zero audit_logs rows for any of them.
    #
    # Written here rather than by opting Patient into listeners.py on purpose.
    # patients/service.py:368 states why: update_patient() already writes its
    # own row, so flipping the automatic opt-in would double-write every update
    # the moment the B7 rollout lands. This closes the create gap without
    # colliding with that rollout.
    #
    # IDENTIFIERS ONLY, NEVER THE PERSONAL DATA. audit_logs is append-only
    # (0004's trigger), so anything copied in cannot be erased — and a DPDP
    # erasure request has to be satisfiable. Recording full_name/mobile/dob
    # here would build a second, indelible copy of exactly the data the patient
    # can demand be deleted. Who created which record is the compliance
    # question; duplicating the record is not.
    await write_audit_log(
        db,
        facility_id=patient.facility_id,
        action=AuditAction.CREATE,
        resource_type="patients",
        user_id=current_db_user.id,
        resource_id=patient.id,
        patient_id=patient.id,
        new_value={
            "uhid": patient.uhid,
            "identity_path": patient.identity_path,
            "identity_status": patient.identity_status,
        },
    )

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
    # Doctor and nurse workspaces reuse the same masked, facility-scoped picker
    # for consent. Advertising /consent to them while denying this prerequisite
    # made the screen fail before it could request a single consent record.
    dependencies=[Depends(require_roles("receptionist", "doctor", "nurse", "admin"))],
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
    """Update a patient record.

    row_version is incremented on every mutation (optimistic concurrency §4A.2).
    If-Match enforcement (reject stale writes) is staged for a follow-up — the
    column and increment are wired; the header check is not yet implemented.
    """
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
            caller_facility_id=current_db_user.facility_id,
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
        return await approve_merge(
            db, merge_log_id=merge_id, approved_by=current_db_user.id,
            caller_facility_id=current_db_user.facility_id,
        )
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
            caller_facility_id=current_db_user.facility_id,
        )
    except ValueError as e:
        if str(e) == "self_approval_not_allowed":
            raise HTTPException(409, {"code": "self_approval_not_allowed"})
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------------------
# [#179] Patient history aggregation — role-filtered, consent-checked, access-logged
# [#228] Personal access history — who accessed this patient's data
# ---------------------------------------------------------------------------
import sqlalchemy as sa

from app.common.enums import AccessChannel
from app.consent.access_log import log_patient_data_access
from app.consent.models import DataAccessLog
from app.consent.service import evaluate_clinical_access
from app.patients.history_service import get_patient_history

_HISTORY_ROLES = ("doctor", "nurse", "receptionist", "admin")


@router.get(
    "/{patient_id}",
    response_model=PatientDetailOut,
    dependencies=[
        Depends(
            log_patient_data_access(
                resource_type="patients",
                purpose_code="clinical_review",
                access_channel=AccessChannel.API.value,
                consent_required=False,
            )
        ),
        Depends(require_roles(*_HISTORY_ROLES)),
    ],
    summary="One patient record by id — the header every clinical screen opens with",
)
async def get_patient_endpoint(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> PatientDetailOut:
    """This did not exist.

    A patient could be created, searched, updated, and have their history,
    consents, ABHA and access-history read — but the record itself could not be
    fetched by id. Every clinical screen opens with "load this patient", and
    `PATCH /patients/{id}` implies an edit form that has to populate from
    somewhere. The frontend's `getPatient` mock was standing in for it.

    Declared *below* the /{patient_id}/... sub-routes in this file but that is
    not what decides matching — FastAPI matches on the full path, and
    "/{patient_id}" cannot capture "/{patient_id}/history". The literal
    "/ping", "/search" and "/merge" routes are the ones that must stay above
    this, and they do.

    consent_required=False, unlike /history: this returns the demographic
    header a clinician needs to confirm they have the right person in front of
    them, not the clinical record. The access is still logged. If that framing
    is wrong it is a policy decision, not a code one — flag it.
    """
    patient = await db.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise HTTPException(404, {"code": "patient_not_found"})
    if patient.facility_id != current_db_user.facility_id:
        # 404 not 403 — 403 confirms the id exists, which enumerates another
        # facility's patients.
        raise HTTPException(404, {"code": "patient_not_found"})

    # §3 0006 merge repointing rule: every patient read resolves the merge
    # pointer, the same as /history above. A caller holding a pre-merge id must
    # land on the surviving record rather than a tombstone, or they will chart
    # against a patient that no longer accumulates data.
    merged_from_id: uuid.UUID | None = None
    if patient.status == "merged" and patient.merged_into_patient_id:
        merged_from_id = patient.id
        canonical = await db.get(Patient, patient.merged_into_patient_id)
        if canonical is None or canonical.deleted_at is not None:
            raise HTTPException(404, {"code": "patient_not_found"})
        if canonical.facility_id != current_db_user.facility_id:
            raise HTTPException(404, {"code": "patient_not_found"})
        patient = canonical

    detail = PatientDetailOut.model_validate(patient)
    detail.merged_from_patient_id = merged_from_id
    return detail


@router.get(
    "/{patient_id}/history",
    dependencies=[
        Depends(
            log_patient_data_access(
                resource_type="patient_history",
                purpose_code="clinical_review",
                access_channel=AccessChannel.API.value,
                consent_required=True,
            )
        ),
        Depends(require_roles(*_HISTORY_ROLES)),
    ],
    summary="[#179] Aggregated patient history — role-filtered, consent-checked, access-logged",
)
async def get_patient_history_endpoint(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    patient = await db.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise HTTPException(404, {"code": "patient_not_found"})
    if patient.facility_id != current_db_user.facility_id:
        raise HTTPException(404, {"code": "patient_not_found"})

    # §3 0006 merge repointing rule: every patient read resolves the merge
    # pointer. Follow the chain to the canonical record.
    merged_from_id: uuid.UUID | None = None
    if patient.status == "merged" and patient.merged_into_patient_id:
        merged_from_id = patient.id
        canonical = await db.get(Patient, patient.merged_into_patient_id)
        if canonical is None or canonical.deleted_at is not None:
            raise HTTPException(404, {"code": "patient_not_found"})
        if canonical.facility_id != current_db_user.facility_id:
            raise HTTPException(404, {"code": "patient_not_found"})
        patient_id = canonical.id

    access = await evaluate_clinical_access(
        db,
        patient_id=patient_id,
        user_id=current_db_user.id,
    )
    if not access.allowed:
        raise HTTPException(
            403,
            {
                "code": "consent_required",
                "blocked_reason": access.blocked_reason,
                "break_glass_available": "doctor" in current_db_user.roles,
            },
        )

    # Explicit priority list — set iteration is non-deterministic.
    # doctor > nurse > receptionist/admin.
    _ROLE_PRIORITY = ["doctor", "nurse", "receptionist", "admin"]
    role_set = set(current_db_user.roles)
    resolved_role = next((r for r in _ROLE_PRIORITY if r in role_set), "receptionist")

    history = await get_patient_history(
        db,
        patient_id=patient_id,
        role=resolved_role,
    )

    if merged_from_id is not None:
        history["merged_from_patient_id"] = str(merged_from_id)

    return history


@router.get(
    "/{patient_id}/access-history",
    dependencies=[Depends(require_roles("auditor", "admin", "doctor"))],
    summary="[#228] Personal access history — who accessed this patient's data",
)
async def get_patient_access_history(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
) -> dict:
    patient = await db.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise HTTPException(404, {"code": "patient_not_found"})
    if patient.facility_id != current_db_user.facility_id:
        raise HTTPException(404, {"code": "patient_not_found"})

    rows = (
        await db.execute(
            sa.select(DataAccessLog)
            .where(DataAccessLog.patient_id == patient_id)
            .order_by(DataAccessLog.accessed_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    total = (
        await db.execute(
            sa.select(sa.func.count()).select_from(DataAccessLog).where(
                DataAccessLog.patient_id == patient_id
            )
        )
    ).scalar_one()

    return {
        "patient_id": str(patient_id),
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "accessed_at": r.accessed_at.isoformat(),
                "user_id": str(r.user_id),
                "role": r.role,
                "resource_type": r.resource_type,
                "purpose_code": r.purpose_code,
                "access_channel": r.access_channel,
                "emergency_access": r.emergency_access,
                "consent_required": r.consent_required,
                "consent_verified": r.consent_verified,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# [#228] Patient portal — own ABHA data
# ---------------------------------------------------------------------------

@router.get(
    "/{patient_id}/abha",
    dependencies=[Depends(require_roles("auditor", "admin", "doctor"))],
    summary="View a patient's ABHA linking data (staff audit)",
)
async def get_patient_abha(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Returns the patient's ABHA number and linking status.

    abha_linking_token_encrypted is NEVER returned — it is a credential,
    not a display field (schema §7: never return encrypted PII fields).
    abha_number is returned as-is per schema §7: "plaintext by design,
    it is a health ID, never a key".

    This route accepts a patient ID, so it is staff-only. Portal access must
    use a self endpoint whose patient ID comes from an authenticated
    account-to-patient binding; that binding is not in the current schema.
    """
    patient = await db.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise HTTPException(404, {"code": "patient_not_found"})
    if patient.facility_id != current_db_user.facility_id:
        raise HTTPException(404, {"code": "patient_not_found"})

    return {
        "patient_id": str(patient_id),
        "abha_number": patient.abha_number,
        # 0030 columns — present only if migration 0030 has landed (B1).
        # Guard with getattr so this endpoint doesn't 500 on envs where
        # 0030 hasn't run yet.
        "abha_linked_at": (
            getattr(patient, "abha_linked_at", None).isoformat()
            if getattr(patient, "abha_linked_at", None) else None
        ),
        "abha_linking_key_version": getattr(patient, "abha_linking_key_version", None),
        # Linking token encrypted is a credential — never returned.
    }


# ---------------------------------------------------------------------------
# [#228] Patient portal — own consent list
# ---------------------------------------------------------------------------
import importlib as _il
_consent_service = _il.import_module("app.consent.service")

from app.consent.schemas import ConsentRecordOut


@router.get(
    "/{patient_id}/consents",
    response_model=list[ConsentRecordOut],
    dependencies=[
        Depends(
            log_patient_data_access(
                resource_type="consent_records",
                purpose_code="self_review",
                access_channel=AccessChannel.API.value,
                consent_required=False,
            )
        ),
        Depends(require_roles("auditor", "admin", "doctor")),
    ],
    summary="View a patient's consent records (staff audit)",
)
async def get_patient_consents(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> list[ConsentRecordOut]:
    """Patient's own consent records, scoped to their facility.

    Viewing one's own consent log is not itself consent-gated
    (consent_required=False) — same ruling as consent/router.py's
    existing /patients/{id}/records endpoint.

    This patient-ID route is staff-only. A portal caller must never be able to
    select a patient ID from the URL.
    """
    patient = await db.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise HTTPException(404, {"code": "patient_not_found"})
    if patient.facility_id != current_db_user.facility_id:
        raise HTTPException(404, {"code": "patient_not_found"})

    records = await _consent_service.list_consent_records_for_patient(
        db, patient_id, facility_id=current_db_user.facility_id
    )
    return [ConsentRecordOut.model_validate(r) for r in records]

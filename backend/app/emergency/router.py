"""Emergency module router — THID issuance and THID→UHID promotion (W5-01).

Role rules (schema doc §Account governance, v3.8):
  - register: receptionist | admin | nurse (ED desk staff)
  - promote (request): supervisor
  - promote (approve): supervisor, different person from requester
  - unmerge: supervisor, different person from approver
  - superadmin is BARRED from all merge/unmerge (no clinical access)
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.audit.context import AuditActor
from app.audit.deps import get_current_actor_dependency
from app.audit.service import write_audit_log
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.emergency.schemas import (
    EmergencyPatientCreate, EmergencyPatientOut,
    PromotionOut, PromotionRequest, UnmergeRequest,
)
from app.emergency.service import (
    approve_promotion, generate_thid,
    request_promotion, unmerge_promotion,
)
from app.patients.models import Patient
from app.users.models import Facility

router = APIRouter(prefix="/emergency", tags=["emergency"])


# Module-liveness stub. Gated on `admin` for the same reason ot/, outbox/,
# blood_bank/, registration/ and security_audit/ already are: an
# unauthenticated endpoint on a health system is a finding regardless of
# payload, and the response still discloses which modules exist — useful
# reconnaissance, useless to a legitimate caller.
#
# Fourteen of these were still public after the WASA M4 pass closed five of
# them, so `make contract`-style module enumeration remained available to
# anyone who could reach the host. Nothing consumes them: no frontend call, no
# e2e script, no compose healthcheck (those probe Mongo and Redis directly),
# no Grafana panel.
@router.get("/ping", dependencies=[Depends(require_roles("admin"))])
async def ping() -> dict:
    return {"module": "emergency", "status": "ok"}


@router.post(
    "/patients",
    status_code=201,
    response_model=EmergencyPatientOut,
    dependencies=[Depends(require_roles("emergency", "receptionist", "admin", "nurse"))],
)
async def register_emergency_patient(
    payload: EmergencyPatientCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> Patient:
    """Register an unidentified/critical patient with a THID.

    facility_id is sourced from current_db_user — never from the request
    payload, so a nurse at facility A cannot register into facility B.
    full_name defaults to 'Unknown (<thid>)' when not supplied.
    """
    facility = await db.get(Facility, current_db_user.facility_id)
    if not facility:
        raise HTTPException(404, "Facility not found")

    thid = await generate_thid(
        db,
        facility_code=facility.code,
        facility_timezone=facility.timezone,
    )

    patient = Patient(
        thid=thid,
        full_name=payload.full_name or f"Unknown ({thid})",
        sex=payload.sex,
        age_years=payload.age_years,
        mobile=payload.mobile,
        facility_id=current_db_user.facility_id,  # from token, not payload
        identity_path="thid",
        identity_status="identity_unverified",
        created_by=current_db_user.id,
    )
    db.add(patient)
    await db.flush()
    await db.refresh(patient)

    # DPDP data-access logging (#290). Same gap as POST /patients, and named separately because the
    # unit of repair is the route family, not the one route reported. Creating a
    # patient record is the first
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
            "thid": patient.thid,
            "identity_path": patient.identity_path,
            "identity_status": patient.identity_status,
        },
    )
    return patient


@router.post(
    "/patients/{patient_id}/promote",
    status_code=201,
    response_model=PromotionOut,
    dependencies=[Depends(require_roles("supervisor"))],
)
async def request_thid_promotion(
    patient_id: uuid.UUID,
    payload: PromotionRequest,
    current_db_user: CurrentDbUser,
    actor: AuditActor = Depends(get_current_actor_dependency),
    db: AsyncSession = Depends(get_db),
) -> PromotionOut:
    """Supervisor requests THID→UHID promotion. A second supervisor must approve."""
    try:
        return await request_promotion(
            db,
            patient_id=patient_id,
            facility_id=current_db_user.facility_id,
            reason=payload.reason,
            requested_by=current_db_user.id,
        )
    except ValueError as e:
        code = str(e)
        if code == "patient_not_found":
            raise HTTPException(404, {"code": "patient_not_found"})
        if code == "patient_not_thid":
            raise HTTPException(409, {"code": "patient_not_thid",
                "message": "Patient is not on the THID identity path"})
        if code.startswith("patient_not_active"):
            raise HTTPException(409, {"code": "patient_not_active"})
        if code == "promotion_already_pending":
            raise HTTPException(409, {"code": "promotion_already_pending",
                "message": "A promotion request is already pending for this patient"})
        raise HTTPException(400, str(e))


@router.post(
    "/patients/promotions/{merge_log_id}/approve",
    response_model=PromotionOut,
    dependencies=[Depends(require_roles("supervisor"))],
)
async def approve_thid_promotion(
    merge_log_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    actor: AuditActor = Depends(get_current_actor_dependency),
    db: AsyncSession = Depends(get_db),
) -> PromotionOut:
    """Different supervisor approves — generates UHID, updates patient."""
    facility = await db.get(Facility, current_db_user.facility_id)
    if not facility:
        raise HTTPException(404, "Facility not found")
    try:
        return await approve_promotion(
            db,
            merge_log_id=merge_log_id,
            facility_id=current_db_user.facility_id,
            approved_by=current_db_user.id,
            state_code=facility.state_code,
            facility_code=facility.code,
            facility_timezone=facility.timezone,
        )
    except ValueError as e:
        code = str(e)
        if code == "self_approval_not_allowed":
            raise HTTPException(409, {"code": "self_approval_not_allowed"})
        if code == "merge_log_not_found":
            raise HTTPException(404, {"code": "merge_log_not_found"})
        if code in ("patient_already_promoted", "patient_already_has_uhid"):
            raise HTTPException(409, {"code": code})
        if code.startswith("not_pending"):
            raise HTTPException(409, {"code": "not_pending"})
        raise HTTPException(400, str(e))


@router.post(
    "/patients/promotions/{merge_log_id}/unmerge",
    response_model=PromotionOut,
    dependencies=[Depends(require_roles("supervisor"))],
)
async def unmerge_thid_promotion(
    merge_log_id: uuid.UUID,
    payload: UnmergeRequest,
    current_db_user: CurrentDbUser,
    actor: AuditActor = Depends(get_current_actor_dependency),
    db: AsyncSession = Depends(get_db),
) -> PromotionOut:
    """Supervisor (different from approver) reverses an approved THID promotion."""
    try:
        return await unmerge_promotion(
            db,
            merge_log_id=merge_log_id,
            facility_id=current_db_user.facility_id,
            unmerged_by=current_db_user.id,
            unmerge_reason=payload.reason,
        )
    except ValueError as e:
        code = str(e)
        if code == "self_unmerge_not_allowed":
            raise HTTPException(409, {"code": "self_unmerge_not_allowed",
                "message": "The supervisor who approved cannot also unmerge (maker-checker)"})
        if code == "merge_log_not_found":
            raise HTTPException(404, {"code": "merge_log_not_found"})
        if code.startswith("not_approved"):
            raise HTTPException(409, {"code": "not_approved"})
        raise HTTPException(400, str(e))

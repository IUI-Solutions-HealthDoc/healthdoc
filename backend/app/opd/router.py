"""
backend/app/opd/router.py

/visits endpoints. Response fields follow §4.4 of the schema doc.

Fixes applied (2026-08-03 review):
  1. created_by/updated_by now come from current_user, never from the
     request body -- the old code let any caller attribute a write to
     an arbitrary user UUID.
  2. Idempotency-Key is now mandatory on POST (§4A.1). A retried
     registration replays the stored response instead of creating a
     second visit.
  3. PATCH .../status now requires If-Match: <row_version> and returns
     409 stale_write on mismatch (§4A.2), instead of silently
     overwriting a concurrent edit.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.auth.deps import CurrentDbUser, require_roles, get_current_user
from app.audit.actions import AuditAction
from app.audit.service import write_audit_log
from app.common.db import get_db
# check_idempotency / record_idempotent_response, NOT consume_/store_. This
# branch carried its own app/common/idempotency.py with a different API;
# staging's won the merge because it keys on (key, user_id, endpoint) per
# 0003a, where this branch's keyed on (key, endpoint) — which would hand one
# user another user's stored response.
from app.common.idempotency import (
    check_idempotency, hash_request_body, record_idempotent_response,
)
from app.opd import service
from app.opd.schemas import VisitCreate, VisitOut, VisitStatusUpdate, VisitTypeUpdate
from app.users.models import Facility

router = APIRouter(prefix="/visits", tags=["visits"])


@router.post(
    "",
    response_model=VisitOut,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def create_visit(
    payload: VisitCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail={"code": "idempotency_key_required", "message": "Idempotency-Key header is required"},
        )

    endpoint = "POST /visits"
    cached = await check_idempotency(
        db,
        idempotency_key,
        endpoint,
        hash_request_body(payload),
        user_id=current_db_user.id,
    )
    if cached is not None:
        return cached.response_body

    # The caller's facility, from their token — never payload.facility_id.
    # POST /patients already documents this rule; /visits had the same hole
    # open, and a visit carries a registration invoice with it, so the body
    # value could open a billable record at another facility.
    #
    # A disagreeing body value is refused rather than quietly ignored: silently
    # accepting it would leave no trace of an attempted cross-facility write.
    facility_id = current_db_user.facility_id
    if payload.facility_id is not None and payload.facility_id != facility_id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "code": "facility_mismatch",
                "message": "facility_id must match the authenticated user's facility",
            },
        )

    facility_code, facility_timezone = await _get_facility_code_and_timezone(db, facility_id)

    visit = await service.create_visit(
        db=db,
        payload=payload,
        facility_code=facility_code,
        facility_timezone=facility_timezone,
        created_by=current_db_user.id,
        facility_id=facility_id,
    )
    await db.commit()

    visit_out = VisitOut.model_validate(visit)
    await record_idempotent_response(
        db,
        idempotency_key,
        endpoint,
        http_status.HTTP_201_CREATED,
        visit_out.model_dump(mode="json"),
        user_id=current_db_user.id,
    )
    await db.commit()
    return visit_out


@router.get(
    "/{visit_id}",
    response_model=VisitOut,
    # This route carried no role dependency at all — only get_current_user — so
    # any authenticated account of any role could read any visit in the
    # deployment by id, including its patient_id and visit_number.
    dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "admin"))],
)
async def get_visit(
    visit_id: UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
):
    visit = await service.get_visit(db, visit_id)
    # 404 rather than 403 for a visit at another facility: 403 confirms the id
    # exists, which is enough to enumerate another hospital's visits.
    if visit is None or visit.facility_id != current_db_user.facility_id:
        raise HTTPException(status_code=404, detail="Visit not found")
    return visit


@router.patch(
    "/{visit_id}/type",
    response_model=VisitOut,
    dependencies=[Depends(require_roles("receptionist", "doctor", "admin"))],
    summary="Reclassify a visit (OPD / IPD / day care / emergency / teleconsult)",
)
async def update_visit_type(
    visit_id: UUID,
    payload: VisitTypeUpdate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    """Change what kind of episode of care this visit is.

    Both the front desk and the clinician may do this: reception books what the
    patient asked for, and the doctor is the one who discovers it should have
    been an admission. Restricting it to either alone means the correction
    waits for someone who is not in the room.

    Same If-Match concurrency rule as the status transition beside it — two
    people reclassifying the same visit must not silently overwrite each other.
    """
    visit = await service.get_visit(db, visit_id)
    if visit is None or visit.facility_id != current_db_user.facility_id:
        raise HTTPException(status_code=404, detail="Visit not found")

    if if_match is None:
        raise HTTPException(
            status_code=428,
            detail={"code": "if_match_required", "message": "If-Match header is required"},
        )
    try:
        expected_version = int(if_match)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_if_match", "message": "If-Match must be an integer row_version"},
        )
    if expected_version != visit.row_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "stale_write",
                "message": "Visit was modified by another user",
                "current": VisitOut.model_validate(visit).model_dump(mode="json"),
            },
        )

    try:
        visit, previous = await service.change_visit_type(
            db,
            visit=visit,
            new_type=payload.visit_type,
            reason=payload.reason,
            updated_by=current_db_user.id,
        )
    except service.InvalidVisitTypeChange as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "invalid_visit_type_change", "message": str(exc)},
        )

    # Reclassification moves money and bed counts, so it is audited explicitly
    # rather than left to the listener — `reason` is request-level intent the
    # column diff cannot see.
    await write_audit_log(
        db,
        facility_id=visit.facility_id,
        action=AuditAction.UPDATE,
        resource_type="visits",
        user_id=current_db_user.id,
        resource_id=visit.id,
        patient_id=visit.patient_id,
        visit_id=visit.id,
        old_value={"visit_type": previous},
        new_value={"visit_type": visit.visit_type},
        reason=payload.reason,
    )
    return VisitOut.model_validate(visit)


@router.patch(
    "/{visit_id}/status",
    response_model=VisitOut,
    dependencies=[Depends(require_roles("doctor", "receptionist", "admin"))],
)
async def update_visit_status(
    visit_id: UUID,
    payload: VisitStatusUpdate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    visit = await service.get_visit(db, visit_id)
    # Same scope as the GET above. This one is a write: without it, a
    # receptionist could move another facility's visit to cancelled or lwbs.
    if visit is None or visit.facility_id != current_db_user.facility_id:
        raise HTTPException(status_code=404, detail="Visit not found")

    if if_match is None:
        raise HTTPException(
            status_code=428,
            detail={"code": "if_match_required", "message": "If-Match header is required"},
        )
    try:
        expected_version = int(if_match)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_if_match", "message": "If-Match must be an integer row_version"},
        )
    if expected_version != visit.row_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "stale_write",
                "message": "Visit was modified by another user",
                "current": VisitOut.model_validate(visit).model_dump(mode="json"),
            },
        )

    try:
        visit = await service.transition_visit_status(
            db=db,
            visit=visit,
            target_status=payload.status,
            reason=payload.reason,
            updated_by=current_db_user.id,
        )
    except service.InvalidVisitTransition as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "invalid_visit_transition", "message": str(exc)},
        ) from exc
    except service.MissingTransitionReason as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "reason_required", "message": str(exc)},
        ) from exc

    await db.commit()
    return visit


async def _get_facility_code_and_timezone(db: AsyncSession, facility_id: UUID) -> tuple[str, str]:
    """Look up facilities.code + facilities.timezone (§3-0002). Timezone
    is required so service.create_visit() can compute the business date
    correctly instead of defaulting to UTC (§3 blanket rule)."""
    result = await db.execute(
        select(Facility.code, Facility.timezone).where(Facility.id == facility_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Facility not found")
    return row.code, row.timezone

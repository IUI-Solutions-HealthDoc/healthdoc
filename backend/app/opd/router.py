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
from app.opd.schemas import VisitCreate, VisitOut, VisitStatusUpdate
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

    facility_code, facility_timezone = await _get_facility_code_and_timezone(db, payload.facility_id)

    visit = await service.create_visit(
        db=db,
        payload=payload,
        facility_code=facility_code,
        facility_timezone=facility_timezone,
        created_by=current_db_user.id,
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


@router.get("/{visit_id}", response_model=VisitOut)
async def get_visit(
    visit_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    visit = await service.get_visit(db, visit_id)
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found")
    return visit


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
    if visit is None:
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

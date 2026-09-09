"""Facility-scoped identifier-only delivery operations; never a clinical inbox."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.integrations.abdm.jobs import AbdmJob

router = APIRouter(
    prefix="/abdm/operations",
    tags=["abdm-operations"],
    dependencies=[Depends(require_roles("admin"))],
)
DbSession = Annotated[AsyncSession, Depends(get_db)]


def require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
) -> str:
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(400, {"code": "idempotency_key_required"})
    return idempotency_key


IdempotencyKey = Annotated[str, Depends(require_idempotency_key)]


class RetryBody(BaseModel):
    """The retry endpoint intentionally takes no mutable business payload."""


class JobOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    attempts: int
    available_at: datetime
    last_error: str | None


def public_job(job: AbdmJob) -> JobOut:
    return JobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        attempts=job.attempts,
        available_at=job.available_at,
        last_error=job.last_error,
    )


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(
    current_db_user: CurrentDbUser,
    db: DbSession,
    status: Literal["pending", "leased", "done", "dead"] = "dead",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[JobOut]:
    rows = (
        (
            await db.execute(
                select(AbdmJob)
                .where(
                    AbdmJob.facility_id == current_db_user.facility_id,
                    AbdmJob.status == status,
                )
                .order_by(AbdmJob.available_at, AbdmJob.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [public_job(row) for row in rows]


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
async def retry_job(
    job_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: IdempotencyKey,
) -> JobOut:
    job = (
        await db.execute(
            select(AbdmJob)
            .where(
                AbdmJob.id == job_id,
                AbdmJob.facility_id == current_db_user.facility_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, {"code": "not_found", "message": "No such delivery job"})
    endpoint = f"POST /abdm/operations/jobs/{job_id}/retry"
    replay = await check_idempotency(
        db, idempotency_key, endpoint, hash_request_body(RetryBody()), current_db_user.id
    )
    if replay is not None:
        return JobOut.model_validate(replay.response_body)
    if job.status == "pending":
        output = public_job(job)
        await record_idempotent_response(
            db, idempotency_key, endpoint, 200, output.model_dump(mode="json"), current_db_user.id
        )
        return output  # A new operator request must not reset active attempts.
    if job.status != "dead":
        raise HTTPException(
            409, {"code": "job_not_retryable", "message": "Only exhausted jobs can be retried"}
        )
    job.status, job.attempts, job.last_error = "pending", 0, None
    job.available_at = datetime.now(UTC)
    job.lease_token = job.lease_until = None
    from app.audit.actions import AuditAction
    from app.audit.service import write_audit_log

    await write_audit_log(
        db,
        facility_id=current_db_user.facility_id,
        user_id=current_db_user.id,
        action=AuditAction.UPDATE,
        resource_type="abdm_jobs",
        resource_id=job.id,
        reason="Operator retried exhausted delivery; worker will recheck authority",
    )
    await db.flush()
    output = public_job(job)
    await record_idempotent_response(
        db, idempotency_key, endpoint, 200, output.model_dump(mode="json"), current_db_user.id
    )
    return output


class ReconcileIn(BaseModel):
    context_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    apply: bool = False


class ReconcileOut(BaseModel):
    context_id: uuid.UUID
    status: str
    document_at: datetime | None = None
    reason: str | None = None


@router.post("/contexts/reconcile", response_model=list[ReconcileOut])
async def reconcile_contexts(
    payload: ReconcileIn,
    current_db_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: IdempotencyKey,
) -> list[ReconcileOut]:
    """Preview by default. Only reconcile explicit, canonical single documents.

    Visit-wide or invented references remain refused. Never rewrite a date
    already adopted by a document, or expand a confirmed link's references.
    """
    from app.integrations.abdm.hip.documents import DocumentUnavailable, resolve_document
    from app.integrations.abdm.hip.models import AbdmCareContext
    from app.integrations.abdm.jobs import enqueue

    rows = (
        (
            await db.execute(
                select(AbdmCareContext)
                .where(
                    AbdmCareContext.id.in_(payload.context_ids),
                    AbdmCareContext.facility_id == current_db_user.facility_id,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    by_id = {row.id: row for row in rows}
    endpoint = f"POST /abdm/operations/contexts/reconcile/{current_db_user.facility_id}"
    replay = await check_idempotency(
        db, idempotency_key, endpoint, hash_request_body(payload), current_db_user.id
    )
    if replay is not None:
        return [ReconcileOut.model_validate(row) for row in replay.response_body["items"]]
    output = []
    for ident in dict.fromkeys(payload.context_ids):
        row = by_id.get(ident)
        if row is None:
            output.append(ReconcileOut(context_id=ident, status="unavailable"))
            continue
        if row.document_at is not None:
            output.append(
                ReconcileOut(context_id=ident, status="unchanged", document_at=row.document_at)
            )
            continue
        try:
            source = await resolve_document(
                db,
                reference=row.reference,
                hi_type=row.hi_type,
                patient_id=row.patient_id,
                facility_id=row.facility_id,
                visit_id=row.visit_id,
            )
        except DocumentUnavailable as exc:
            output.append(ReconcileOut(context_id=ident, status="refused", reason=str(exc)))
            continue
        if payload.apply:
            row.document_at = source.authored_at
            row.updated_by = current_db_user.id
            await enqueue(db, kind="context_notify", target_id=row.id, facility_id=row.facility_id)
        output.append(
            ReconcileOut(
                context_id=ident,
                status="reconciled" if payload.apply else "eligible",
                document_at=source.authored_at,
            )
        )
    await db.flush()
    await record_idempotent_response(
        db,
        idempotency_key,
        endpoint,
        200,
        {"items": [row.model_dump(mode="json") for row in output]},
        current_db_user.id,
    )
    return output

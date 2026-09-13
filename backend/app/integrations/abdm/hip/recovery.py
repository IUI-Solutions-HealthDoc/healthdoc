"""Explicit operator recovery for one completed dispatch with a missing callback.

This does not run a worker or invent a new REQUEST-ID. It only requeues the
original job after inspection. No automatic timer calls it: generating tokens
repeatedly can block a facility/address for 24 hours (M2 v2.8).
Job completion alone does not prove the historical HTTP response was accepted;
inspect independent transport evidence and obtain transmission permission first.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.audit.service import write_audit_log
from app.integrations.abdm.hip.documents import DocumentUnavailable, resolve_context_document
from app.integrations.abdm.hip.linking import demographics
from app.integrations.abdm.hip.models import AbdmCareContext, AbdmCareContextLink
from app.integrations.abdm.jobs import TOKEN_CALLBACK_RECOVERY_MARKER, AbdmJob, job_id
from app.patients.models import Patient


async def queue_token_callback_retry(
    db: AsyncSession, *, link_id: uuid.UUID, facility_id: uuid.UUID, apply: bool = False
) -> uuid.UUID:
    """Preview by default; caller commits the exact job and its audit together.

    Ten minutes is a conservative LOCAL waiting period, not an NHA SLA. Permit
    just one recovery, and abstain if other token requests for this address
    already consumed the local daily budget. Do not use this for gateway
    refusals, expired tokens, confirmed links, or a changed patient/document.
    """
    now = datetime.now(UTC)
    link = (
        await db.execute(
            select(AbdmCareContextLink)
            .where(
                AbdmCareContextLink.id == link_id, AbdmCareContextLink.facility_id == facility_id
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if link is None:
        raise DocumentUnavailable("Link unavailable")
    if (
        link.status != "pending"
        or link.link_token_encrypted is not None
        or link.token_use_until is not None
        or link.failure_reason is not None
    ):
        raise DocumentUnavailable("Only a pending link with no token or refusal can be recovered")
    ident = job_id("link_token", link.id)
    job = (
        await db.execute(select(AbdmJob).where(AbdmJob.id == ident).with_for_update())
    ).scalar_one_or_none()
    if (
        job is None
        or job.facility_id != facility_id
        or job.target_id != link.id
        or job.kind != "link_token"
        or job.status != "done"
        or job.attempts != 1
        or job.last_error is not None
        or link.token_request_id != str(ident)
        or job.lease_token is not None
        or job.lease_until is not None
    ):
        raise DocumentUnavailable("Recovery requires exactly one completed token dispatch")
    if job.updated_at > now - timedelta(minutes=10):
        raise DocumentUnavailable("Wait at least ten minutes for the original callback")
    if await db.get(AbdmJob, job_id("link_context", link.id)) is not None:
        raise DocumentUnavailable("Link-context work already exists; do not regenerate a token")
    patient = await db.get(Patient, link.patient_id)
    if (
        patient is None
        or patient.facility_id != facility_id
        or patient.abha_address != link.abha_address
    ):
        raise DocumentUnavailable("Patient identity changed during linking")
    demographics(patient)
    recent = (
        (
            await db.execute(
                select(AbdmJob)
                .join(AbdmCareContextLink, AbdmCareContextLink.id == AbdmJob.target_id)
                .where(
                    AbdmJob.kind == "link_token",
                    AbdmJob.facility_id == facility_id,
                    AbdmCareContextLink.facility_id == facility_id,
                    AbdmCareContextLink.abha_address == link.abha_address,
                    AbdmJob.updated_at >= now - timedelta(hours=24),
                )
            )
        )
        .scalars()
        .all()
    )
    if any(row.id != ident for row in recent):
        raise DocumentUnavailable("Other recent token requests exist; ask NHA before retrying")
    contexts = (
        (
            await db.execute(
                select(AbdmCareContext).where(
                    AbdmCareContext.facility_id == facility_id,
                    AbdmCareContext.patient_id == patient.id,
                    AbdmCareContext.reference.in_(link.care_context_references),
                )
            )
        )
        .scalars()
        .all()
    )
    if not contexts or len(contexts) != len(link.care_context_references):
        raise DocumentUnavailable("Original documents are unavailable")
    for context in contexts:
        await resolve_context_document(db, context)
    if apply:
        job.status = "pending"
        job.available_at = now
        job.last_error = TOKEN_CALLBACK_RECOVERY_MARKER
        await write_audit_log(
            db,
            facility_id=facility_id,
            action=AuditAction.UPDATE,
            resource_type="abdm_jobs",
            resource_id=job.id,
            reason=TOKEN_CALLBACK_RECOVERY_MARKER
            + "; original REQUEST-ID retained; local operator maintenance",
        )
        await db.flush()
    return ident

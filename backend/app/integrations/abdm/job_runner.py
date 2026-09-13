"""Run with python -m app.integrations.abdm.job_runner after migrations.

The HTTP background task is only a latency optimization. This polling process
is what recovers accepted work after an API process dies or reloads.
"""

import argparse
import asyncio
import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.common.config import get_settings
from app.common.db import SessionLocal
from app.integrations.abdm import jobs
from app.integrations.abdm.client import AbdmAuthError, AbdmProtocolError, safe_failure_summary
from app.integrations.abdm.hip import gateway, linking, worker
from app.integrations.abdm.hip.documents import DocumentUnavailable, resolve_context_document
from app.integrations.abdm.hip.models import (
    AbdmCareContext,
    AbdmCareContextLink,
    AbdmHipHealthInformationRequest,
)
from app.integrations.abdm.hiu.models import AbdmHiuConsentArtefact, AbdmHiuHealthInformationRequest
from app.integrations.abdm.hiu.service import _clear_key
from app.users.models import Facility

log = logging.getLogger("healthdoc.abdm.jobs")


class DeferredJob(RuntimeError):
    """Waiting for verified patient linkage, not an exhausted transport retry."""


async def notify_context(job: jobs.AbdmJob) -> None:
    async with SessionLocal() as db:
        context = await db.get(AbdmCareContext, job.target_id)
        if context is None or context.facility_id != job.facility_id:
            raise DocumentUnavailable("Context unavailable")
        await resolve_context_document(db, context)
        facility = await db.get(Facility, context.facility_id)
        if facility is None or facility.hfr_facility_id != get_settings().abdm_hfr_facility_id:
            raise DeferredJob("Facility is not configured for this bridge")
        links = (
            (
                await db.execute(
                    select(AbdmCareContextLink).where(
                        AbdmCareContextLink.facility_id == context.facility_id,
                        AbdmCareContextLink.patient_id == context.patient_id,
                        AbdmCareContextLink.status == "confirmed",
                    )
                )
            )
            .scalars()
            .all()
        )
        links = [
            link for link in links if context.reference in (link.care_context_references or [])
        ]
        if not links:
            # A previous link for this patient does NOT implicitly link new
            # documents. G4 must obtain each context's own acknowledgement.
            raise DeferredJob("Document is awaiting confirmed linkage")
        for address in sorted({link.abha_address for link in links}):
            await gateway.notify_care_context(
                abha_address=address,
                care_context_reference=context.reference,
                hi_types=[context.hi_type],
                request_id=str(uuid.uuid5(job.id, address)),
            )


async def _dispatch(job: jobs.AbdmJob) -> None:
    if job.kind == "callback_ack":
        from app.integrations.abdm.callback_replies import dispatch

        await dispatch(job)
    elif job.kind.startswith("hiu_"):
        from app.integrations.abdm.hiu.worker import dispatch

        await dispatch(job)
    elif job.kind in {"link_token", "link_context"}:
        async with SessionLocal() as db:
            link = await db.get(AbdmCareContextLink, job.target_id)
            if link is None or link.facility_id != job.facility_id:
                raise DocumentUnavailable("Link unavailable")
            if link.status != "pending":
                return
            facility = await db.get(Facility, link.facility_id)
            if facility is None or facility.hfr_facility_id != get_settings().abdm_hfr_facility_id:
                raise DeferredJob("Facility is not configured for this bridge")
            if job.kind == "link_context":
                await linking.send_link(db, link)
            else:
                from app.patients.models import Patient

                # A delayed original callback may beat an operator recovery.
                # Never regenerate a credential that is already stored.
                if link.link_token_encrypted is not None:
                    return
                patient = await db.get(Patient, link.patient_id)
                if patient is None or patient.abha_address != link.abha_address:
                    raise DocumentUnavailable("Patient identity changed during linking")
                await gateway.generate_link_token(
                    **linking.demographics(patient), request_id=link.token_request_id
                )
    elif job.kind == "context_notify":
        await notify_context(job)
    elif job.kind == "hip_notify":
        await worker.notify_transaction(job.target_id)
    elif job.kind == "hip_transfer":
        async with SessionLocal() as db:
            row = await db.get(AbdmHipHealthInformationRequest, job.target_id)
            if row is None or row.facility_id != job.facility_id:
                raise worker.TransferError("Transfer unavailable")
            transaction_id = row.transaction_id
        await worker.transfer_transaction(transaction_id, retry_transport=True)
    else:
        raise ValueError("Unsupported ABDM job kind")


async def _heartbeat(ident: uuid.UUID, token: uuid.UUID) -> None:
    while True:
        await asyncio.sleep(30)
        async with SessionLocal() as db:
            if not await jobs.renew(db, ident, token):
                raise RuntimeError("ABDM job lease lost")


async def run_once(ident: uuid.UUID | None = None) -> bool:
    async with SessionLocal() as db:
        job = await jobs.claim(db, ident=ident)
    if job is None:
        return False
    task = asyncio.create_task(_dispatch(job))
    heartbeat = asyncio.create_task(_heartbeat(job.id, job.lease_token))
    error = None
    deferred = False
    terminal = False
    try:
        done, _ = await asyncio.wait({task, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
        if heartbeat in done:
            await heartbeat
        await task
    except DeferredJob as exc:
        error, deferred = str(exc), True
    except Exception as exc:
        # Never persist arbitrary gateway response text or patient content.
        error = safe_failure_summary(exc)
        # Refreshing the gateway session once is already handled by the
        # client. Repeating a refused authorization will not fix its scope or
        # link token, and must not consume the token-generation quota.
        # An unexpected response is not evidence that repeating the operation
        # is safe either. Preserve the diagnostic for deliberate reconciliation.
        terminal = isinstance(exc, AbdmAuthError | AbdmProtocolError)
        log.warning("ABDM job failed (%s)", error)
    finally:
        for pending in (task, heartbeat):
            pending.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await pending
    async with SessionLocal() as db:
        await jobs.finish(db, job, error=error, deferred=deferred, terminal=terminal)
    return True


async def cleanup_expired_keys() -> int:
    """Run even without new callbacks. Lock the same request rows as reception."""
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        from app.integrations.abdm.hiu.records import erase_unusable_content

        erased = await erase_unusable_content(db, now=now)
        rows = (
            (
                await db.execute(
                    select(AbdmHiuHealthInformationRequest)
                    .join(
                        AbdmHiuConsentArtefact,
                        AbdmHiuConsentArtefact.id == AbdmHiuHealthInformationRequest.artefact_id,
                    )
                    .where(
                        AbdmHiuHealthInformationRequest.private_key_encrypted.is_not(None),
                        or_(
                            AbdmHiuHealthInformationRequest.key_expires_at <= now,
                            AbdmHiuConsentArtefact.status != "granted",
                            AbdmHiuConsentArtefact.expires_at.is_(None),
                            AbdmHiuConsentArtefact.expires_at <= now,
                        ),
                    )
                    .with_for_update(of=AbdmHiuHealthInformationRequest, skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            _clear_key(row)
            if row.status not in {"received", "failed"}:
                row.status = "expired"
                row.failure_reason = "Transfer authorisation or key expired"
        links = (
            (
                await db.execute(
                    select(AbdmCareContextLink)
                    .where(
                        AbdmCareContextLink.link_token_encrypted.is_not(None),
                        AbdmCareContextLink.token_use_until <= now,
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for link in links:
            link.link_token_encrypted = None
            link.token_use_until = None
            if link.status == "pending":
                link.status = "expired"
                link.failure_reason = "Link credential use window expired; start linking again"
        replies = list((await db.execute(
            select(jobs.AbdmCallbackReply).where(
                jobs.AbdmCallbackReply.response_encrypted.is_not(None),
                or_(
                    jobs.AbdmCallbackReply.response_expires_at <= now,
                    jobs.AbdmCallbackReply.id.in_(select(jobs.AbdmJob.target_id).where(
                        jobs.AbdmJob.kind == "callback_ack", jobs.AbdmJob.status == "done",
                    )),
                ),
            ).with_for_update(skip_locked=True)
        )).scalars())
        for reply in replies:
            reply.response_encrypted = None
        await db.commit()
        return len(rows) + len(links) + len(replies) + erased


async def run_mode(*, mode: str, once: bool = False) -> None:
    """Cleanup mode never enters the dispatcher, even when outbound jobs exist."""
    if mode == "cleanup":
        if once:
            count = await cleanup_expired_keys()
            log.info("ABDM cleanup completed; cleared items=%s", count)
        else:
            await _poll_cleanup()
    elif mode == "all":
        if once:
            raise ValueError("--once is supported only with --mode cleanup")
        await asyncio.gather(_poll_jobs(), _poll_cleanup())
    else:
        raise ValueError("Unknown ABDM worker mode")


async def main(*, mode: str = "all", once: bool = False) -> None:
    # Load model metadata/listeners as the API does, without running its HTTP server.
    from app import main as app_main  # noqa: F401
    from app.common.security import _get_encryption_key, _get_hmac_key

    _get_encryption_key()
    _get_hmac_key()
    await run_mode(mode=mode, once=once)


async def _poll_cleanup() -> None:
    # Independent of the delivery loop: long transfers cannot postpone key or
    # external-record erasure indefinitely.
    while True:
        try:
            count = await cleanup_expired_keys()
            log.info("ABDM cleanup completed; cleared items=%s", count)
        except Exception as exc:
            log.error("ABDM cleanup failed (%s)", type(exc).__name__)
        await asyncio.sleep(60)


async def _poll_jobs() -> None:
    while True:
        try:
            if not await run_once():
                await asyncio.sleep(2)
        except Exception as exc:
            log.error("ABDM worker cycle failed (%s)", type(exc).__name__)
            await asyncio.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["all", "cleanup"], default="all")
    parser.add_argument("--once", action="store_true", help="Run cleanup once; fail nonzero on errors")
    options = parser.parse_args()
    if options.once and options.mode != "cleanup":
        parser.error("--once requires --mode cleanup")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(mode=options.mode, once=options.once))

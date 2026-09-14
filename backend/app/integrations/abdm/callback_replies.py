"""Durable acknowledgements: never tell the gateway before committing local work.

Correlation metadata is plaintext; bounded M2 reply snapshots are encrypted.
Retries reuse outbound request IDs, including after a process crash mid-reply.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import SessionLocal
from app.common.security import encrypt_pii
from app.integrations.abdm.hip import gateway as hip_gateway
from app.integrations.abdm.hiu import gateway as hiu_gateway
from app.integrations.abdm.hiu.models import AbdmHiuConsentArtefact
from app.integrations.abdm.hiu.worker import _require_configured_facility
from app.integrations.abdm.jobs import AbdmCallbackReply, AbdmJob, enqueue

M2_REPLY_KINDS = frozenset({"hip_discover", "hip_link_init", "hip_link_reject", "hip_profile"})


def response_aad(ident, facility_id, kind) -> bytes:
    return f"abdm:m2-reply:{facility_id}:{kind}:{ident}".encode()


def reply_id(facility_id: uuid.UUID, kind: str, gateway_request_id: str) -> uuid.UUID:
    return uuid.uuid5(
        uuid.NAMESPACE_URL, f"healthdoc:abdm-reply:{facility_id}:{kind}:{gateway_request_id}"
    )


async def schedule(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    kind: Literal[
        "hip_consent",
        "hip_request",
        "hiu_consent",
        "hip_link_confirm",
        "hip_discover",
        "hip_link_init",
        "hip_link_reject",
        "hip_profile",
    ],
    gateway_request_id: str,
    payload: BaseModel,
    subject_ids: list[str],
    target_id: uuid.UUID | None = None,
    response_data: dict | None = None,
    response_expires_at: datetime | None = None,
) -> uuid.UUID:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    ident = reply_id(facility_id, kind, gateway_request_id)
    digest = hashlib.sha256(payload.model_dump_json(by_alias=True).encode()).hexdigest()
    encrypted = None
    expiry = None
    if kind in M2_REPLY_KINDS:
        if response_data is None:
            raise ValueError("M2 response snapshot is required")
        encoded = json.dumps(response_data, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode()) > 256_000:
            raise ValueError("M2 response is too large")
        encrypted = encrypt_pii(encoded, associated_data=response_aad(ident, facility_id, kind))
        expiry = response_expires_at or datetime.now(UTC) + timedelta(minutes=10)
    elif response_data is not None:
        raise ValueError("Unexpected callback response snapshot")
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    await db.execute(
        insert(AbdmCallbackReply)
        .values(
            id=ident,
            facility_id=facility_id,
            kind=kind,
            gateway_request_id=gateway_request_id,
            payload_sha256=digest,
            subject_ids=sorted(set(subject_ids)),
            target_id=target_id,
            response_encrypted=encrypted,
            response_expires_at=expiry,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    reply = await db.get(AbdmCallbackReply, ident)
    if (
        reply.payload_sha256 != digest
        or reply.target_id != target_id
        or reply.subject_ids != sorted(set(subject_ids))
    ):
        raise HTTPException(
            409, {"code": "callback_replay_conflict", "message": "Callback content changed"}
        )
    return await enqueue(db, kind="callback_ack", target_id=ident, facility_id=facility_id)


async def dispatch(job: AbdmJob) -> None:
    async with SessionLocal() as db:
        await _require_configured_facility(db, job)
        reply = await db.get(AbdmCallbackReply, job.target_id)
        if reply is None or reply.facility_id != job.facility_id:
            raise ValueError("Callback reply unavailable")
        if reply.kind in M2_REPLY_KINDS:
            from app.integrations.abdm.m2_replies import dispatch as dispatch_m2

            await dispatch_m2(db, reply, job)
            return
        if reply.kind == "hip_link_confirm":
            # Imports deferred to keep the callback/dispatcher dependency acyclic.
            from app.integrations.abdm.external_router import _groups, _link_patient_contexts
            from app.integrations.abdm.hip.models import AbdmCareContextLink

            link = await db.get(AbdmCareContextLink, reply.target_id)
            if (
                link is None
                or link.facility_id != job.facility_id
                or link.status != "confirmed"
                or link.confirmed_at is None
                or sorted(link.care_context_references) != reply.subject_ids
            ):
                raise ValueError("Confirmed link selection unavailable")
            patient, contexts = await _link_patient_contexts(db, link)
            await hip_gateway.respond_to_link_confirm_groups(
                gateway_request_id=reply.gateway_request_id,
                patient_groups=_groups(patient, contexts),
                request_id=str(job.id),
            )
            return  # An acknowledgement never starts a clinical transfer.
        if reply.kind not in {"hip_request", "hip_consent", "hiu_consent"}:
            raise ValueError("Unsupported callback reply kind")
        for subject in reply.subject_ids:
            request_id = str(uuid.uuid5(job.id, subject))
            if reply.kind == "hip_request":
                await hip_gateway.acknowledge_hi_request(
                    transaction_id=subject,
                    gateway_request_id=reply.gateway_request_id,
                    request_id=request_id,
                )
            else:
                gateway = hip_gateway if reply.kind == "hip_consent" else hiu_gateway
                await gateway.acknowledge_consent_notification(
                    consent_id=subject,
                    gateway_request_id=reply.gateway_request_id,
                    request_id=request_id,
                )
        # Following work is committed AFTER all acknowledgements succeeded.
        # A crash before this commit repeats those same acknowledgement IDs.
        if reply.kind == "hip_request":
            if reply.target_id is None:
                raise ValueError("Transfer target unavailable")
            await enqueue(
                db, kind="hip_transfer", target_id=reply.target_id, facility_id=job.facility_id
            )
        elif reply.kind == "hiu_consent":
            artefacts = (
                (
                    await db.execute(
                        select(AbdmHiuConsentArtefact).where(
                            AbdmHiuConsentArtefact.facility_id == job.facility_id,
                            AbdmHiuConsentArtefact.consent_artefact_id.in_(reply.subject_ids),
                            AbdmHiuConsentArtefact.status == "granted",
                        )
                    )
                )
                .scalars()
                .all()
            )
            for artefact in artefacts:
                await enqueue(
                    db, kind="hiu_fetch", target_id=artefact.id, facility_id=job.facility_id
                )
        await db.commit()

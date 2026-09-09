"""Durable acknowledgements: never tell the gateway before committing local work.

The database stores only correlation IDs and a digest, not the callback's PHI.
Retries reuse outbound request IDs, including after a process crash mid-reply.
"""

import hashlib
import uuid
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import SessionLocal
from app.integrations.abdm.hip import gateway as hip_gateway
from app.integrations.abdm.hiu import gateway as hiu_gateway
from app.integrations.abdm.hiu.models import AbdmHiuConsentArtefact
from app.integrations.abdm.hiu.worker import _require_configured_facility
from app.integrations.abdm.jobs import AbdmCallbackReply, AbdmJob, enqueue


async def schedule(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    kind: Literal["hip_consent", "hip_request", "hiu_consent"],
    gateway_request_id: str,
    payload: BaseModel,
    subject_ids: list[str],
    target_id: uuid.UUID | None = None,
) -> uuid.UUID:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    ident = uuid.uuid5(
        uuid.NAMESPACE_URL, f"healthdoc:abdm-reply:{facility_id}:{kind}:{gateway_request_id}"
    )
    digest = hashlib.sha256(payload.model_dump_json(by_alias=True).encode()).hexdigest()
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
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    reply = await db.get(AbdmCallbackReply, ident)
    if reply.payload_sha256 != digest or reply.target_id != target_id:
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

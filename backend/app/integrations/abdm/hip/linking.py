"""One link operation per explicit selection; token and link IDs never alias.

NHA accepts multiple HI-type groups in patient[]. Generating once per group
wastes its bounded token quota. Each selected context still names one document.
Legacy per-type operations retain their IDs/state on exact idempotent replays.
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.security import decrypt_pii, encrypt_pii
from app.integrations.abdm.hip import gateway
from app.integrations.abdm.hip.documents import DocumentUnavailable, resolve_context_document
from app.integrations.abdm.hip.models import AbdmCareContext, AbdmCareContextLink
from app.integrations.abdm.jobs import enqueue, job_id
from app.patients.models import Patient


def token_aad(link: AbdmCareContextLink) -> bytes:
    return f"abdm:hip-link:{link.facility_id}:{link.id}:{link.abha_address}".encode()


def demographics(patient: Patient) -> dict[str, str]:
    if (
        patient.abha_linked_at is None
        or patient.deleted_at is not None
        or patient.merged_into_patient_id is not None
    ):
        raise DocumentUnavailable("A verified active patient ABHA binding is required")
    gender = {"male": "M", "female": "F", "other": "O"}.get(patient.sex)
    if not patient.abha_address or patient.dob is None or not gender or not patient.full_name:
        raise DocumentUnavailable(
            "ABHA address, date of birth, name and known gender are required for HIP linking"
        )
    return dict(
        abha_address=patient.abha_address,
        name=patient.full_name,
        gender=gender,
        year_of_birth=str(patient.dob.year),
    )


async def initiate(
    db: AsyncSession, *, patient: Patient, context_ids: list[uuid.UUID], idempotency_key: str
) -> list[AbdmCareContextLink]:
    demographics(patient)
    if not context_ids or len(context_ids) != len(set(context_ids)):
        raise DocumentUnavailable("Select distinct finalized documents to link")
    contexts = (
        (
            await db.execute(
                select(AbdmCareContext).where(
                    AbdmCareContext.id.in_(context_ids),
                    AbdmCareContext.facility_id == patient.facility_id,
                    AbdmCareContext.patient_id == patient.id,
                )
            )
        )
        .scalars()
        .all()
    )
    if len(contexts) != len(context_ids):
        raise DocumentUnavailable("One or more selected documents are unavailable")
    for context in contexts:
        await resolve_context_document(db, context)
    references = sorted(context.reference for context in contexts)
    prefix = f"healthdoc:hip-link:{patient.facility_id}:{patient.id}:{idempotency_key}"
    ident = uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}:document-batch")
    # Search ALL old type IDs, not only newly selected types. Otherwise a
    # changed selection could silently reuse an old key for a different ask.
    legacy_ids = [
        uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}:{hi_type}") for hi_type in gateway.HI_TYPES
    ]
    existing = list(
        (
            await db.execute(
                select(AbdmCareContextLink)
                .where(
                    AbdmCareContextLink.id.in_([ident, *legacy_ids]),
                    AbdmCareContextLink.facility_id == patient.facility_id,
                    AbdmCareContextLink.patient_id == patient.id,
                )
                .order_by(AbdmCareContextLink.id)
            )
        ).scalars()
    )
    if existing:
        held = sorted(ref for link in existing for ref in link.care_context_references)
        if (
            held != references
            or any(link.abha_address != patient.abha_address for link in existing)
            or (len(existing) > 1 and any(link.id == ident for link in existing))
        ):
            raise DocumentUnavailable("Idempotency key was already used for different documents")
        return existing  # Never reset old attempts or enqueue a replacement generation.

    link = AbdmCareContextLink(
        id=ident,
        facility_id=patient.facility_id,
        patient_id=patient.id,
        abha_address=patient.abha_address,
        care_context_references=references,
        status="pending",
        token_request_id=str(job_id("link_token", ident)),
        gateway_request_id=str(job_id("link_context", ident)),
    )
    db.add(link)
    await db.flush()
    await enqueue(db, kind="link_token", target_id=link.id, facility_id=link.facility_id)
    return [link]


async def accept_token(
    db: AsyncSession, link: AbdmCareContextLink, token: str, abha_address: str | None
) -> None:
    if abha_address is not None and abha_address != link.abha_address:
        raise DocumentUnavailable("Token identity does not match this link operation")
    if link.status != "pending" or link.link_token_encrypted is not None:
        return
    if not token or len(token) > 16384:
        raise DocumentUnavailable("Link token is missing or too large")
    link.link_token_encrypted = encrypt_pii(token, associated_data=token_aad(link))
    # Local credential-use cap, NOT a claim about NHA token validity. The
    # collection does not supply expiry here; never cache it indefinitely or
    # reinterpret an unverified JWT payload as trusted authorization.
    link.token_use_until = datetime.now(UTC) + timedelta(minutes=5)
    await enqueue(db, kind="link_context", target_id=link.id, facility_id=link.facility_id)


async def send_link(db: AsyncSession, link: AbdmCareContextLink) -> None:
    if link.status != "pending":
        return
    deadline = link.token_use_until
    if deadline is None or (
        deadline if deadline.tzinfo else deadline.replace(tzinfo=UTC)
    ) <= datetime.now(UTC):
        link.status, link.failure_reason = (
            "expired",
            "Link credential use window expired; start linking again",
        )
        link.link_token_encrypted = None
        await db.commit()
        return
    patient = await db.get(Patient, link.patient_id)
    if patient is None or patient.abha_address != link.abha_address:
        raise DocumentUnavailable("Patient identity changed during linking")
    contexts = (
        (
            await db.execute(
                select(AbdmCareContext).where(
                    AbdmCareContext.patient_id == link.patient_id,
                    AbdmCareContext.facility_id == link.facility_id,
                    AbdmCareContext.reference.in_(link.care_context_references),
                )
            )
        )
        .scalars()
        .all()
    )
    if not contexts or len(contexts) != len(link.care_context_references):
        raise DocumentUnavailable("Link operation must identify the complete document selection")
    groups = defaultdict(list)
    for context in contexts:
        await resolve_context_document(db, context)
        groups[context.hi_type].append(
            {"referenceNumber": context.reference, "display": context.display}
        )
    groups = {
        kind: sorted(items, key=lambda item: item["referenceNumber"])
        for kind, items in groups.items()
    }
    selection = (
        {"hi_type": contexts[0].hi_type, "care_contexts": groups[contexts[0].hi_type]}
        if len(groups) == 1
        else {"groups": groups}
    )
    await gateway.link_care_contexts(
        abha_address=link.abha_address,
        link_token=decrypt_pii(link.link_token_encrypted, associated_data=token_aad(link)),
        display=patient.full_name,
        **selection,
        request_id=link.gateway_request_id,
    )

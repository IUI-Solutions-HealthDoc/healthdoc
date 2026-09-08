"""One independent link row per HI-type group; token and link IDs never alias."""

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
    groups = defaultdict(list)
    for context in contexts:
        await resolve_context_document(db, context)
        groups[context.hi_type].append(context.reference)
    links = []
    for hi_type, references in sorted(groups.items()):
        # Each type has independent correlation. Its stored references reject
        # changed retries without aliasing the token and link request IDs.
        ident = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"healthdoc:hip-link:{patient.facility_id}:{patient.id}:{idempotency_key}:{hi_type}",
        )
        link = await db.get(AbdmCareContextLink, ident)
        if link is not None:
            if link.abha_address != patient.abha_address or sorted(
                link.care_context_references
            ) != sorted(references):
                raise DocumentUnavailable(
                    "Idempotency key was already used for different documents"
                )
        else:
            link = AbdmCareContextLink(
                id=ident,
                facility_id=patient.facility_id,
                patient_id=patient.id,
                abha_address=patient.abha_address,
                care_context_references=sorted(references),
                status="pending",
                token_request_id=str(job_id("link_token", ident)),
                gateway_request_id=str(job_id("link_context", ident)),
            )
            db.add(link)
            await db.flush()
            await enqueue(db, kind="link_token", target_id=link.id, facility_id=link.facility_id)
        links.append(link)
    return links


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
    if (
        len(contexts) != len(link.care_context_references)
        or len({c.hi_type for c in contexts}) != 1
    ):
        raise DocumentUnavailable("Link operation must identify one complete HI-type group")
    for context in contexts:
        await resolve_context_document(db, context)
    await gateway.link_care_contexts(
        abha_address=link.abha_address,
        link_token=decrypt_pii(link.link_token_encrypted, associated_data=token_aad(link)),
        display=patient.full_name,
        hi_type=contexts[0].hi_type,
        care_contexts=[{"referenceNumber": c.reference, "display": c.display} for c in contexts],
        request_id=link.gateway_request_id,
    )

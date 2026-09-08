"""HIU (M3) endpoints.

Same two-kinds-of-route split as the HIP router, and the same rule: staff
routes take a bearer token and get their facility from it; gateway routes take
no user. Legacy private callbacks depend on `verify_callback`; official ABDM
v3 callbacks are mounted in `external_router.py` with the gateway's documented
headers and durable transaction checks.

The asymmetry worth noticing is that an HIU is assessed on restraint. A HIP is
judged on whether it refuses to hand over records it should not; an HIU is
judged on whether it asked properly in the first place and can show the
artefact that justified every record it holds. That is why
`request_health_information` will not run without a granted, unexpired artefact
row in this database — not a consent id in the request body, a row we recorded
when the manager told us.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.integrations.abdm import jobs
from app.integrations.abdm.callback_auth import verify_callback
from app.integrations.abdm.hiu import records, service
from app.integrations.abdm.hiu.models import (
    AbdmConsentRequest,
    AbdmHiuConsentArtefact,
    AbdmHiuHealthInformationRequest,
    AbdmReceivedBundle,
)
from app.patients.models import Patient

log = logging.getLogger("healthdoc.abdm.hiu")

router = APIRouter(prefix="/abdm/hiu", tags=["abdm-hiu"])
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _refusal(exc: service.HiuError, status: int = 409) -> HTTPException:
    return HTTPException(status, {"code": exc.code, "message": exc.message})


def _require_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    """Mutations carry one. A retried consent request that opens a second ask
    is a second thing the patient has to answer."""
    if not idempotency_key:
        raise HTTPException(
            400,
            {
                "code": "idempotency_key_required",
                "message": "Idempotency-Key header is required for this request",
            },
        )
    return idempotency_key


IdempotencyKey = Annotated[str, Depends(_require_idempotency_key)]


# =============================================================================
# Staff routes
# =============================================================================


class ConsentRequestIn(BaseModel):
    patient_id: uuid.UUID | None = None
    abha_address: str = Field(min_length=1, max_length=120)
    # Only this purpose has a product-supported outbound mapping. Do not
    # record another purpose locally and silently ask the patient for CAREMGT.
    purpose_code: Literal["CAREMGT"]
    hi_types: list[str]
    date_range_from: datetime
    date_range_to: datetime
    requested_expiry: datetime


class ConsentRequestOut(BaseModel):
    id: uuid.UUID
    status: str
    abha_address: str


@router.post(
    "/consent-requests",
    status_code=201,
    response_model=ConsentRequestOut,
    dependencies=[Depends(require_roles("doctor", "admin"))],
)
async def create_consent_request(
    payload: ConsentRequestIn,
    current_db_user: CurrentDbUser,
    idempotency_key: IdempotencyKey,
    db: DbSession,
) -> ConsentRequestOut:
    """Durably queue an ask; requested is not evidence of patient approval."""
    patient = (
        await db.execute(
            select(Patient)
            .where(
                Patient.id == payload.patient_id,
                Patient.facility_id == current_db_user.facility_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if patient is None:
        raise HTTPException(404, {"code": "not_found", "message": "Patient unavailable"})
    ident = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"healthdoc:hiu-consent:{current_db_user.facility_id}:{current_db_user.id}:{idempotency_key}",
    )
    existing = await db.get(AbdmConsentRequest, ident)
    if existing:
        if (
            existing.patient_id != payload.patient_id
            or existing.abha_address != payload.abha_address
            or existing.hi_types != payload.hi_types
            or existing.purpose_code != payload.purpose_code
            or records.aware(existing.date_range_from) != records.aware(payload.date_range_from)
            or records.aware(existing.date_range_to) != records.aware(payload.date_range_to)
            or records.aware(existing.requested_expiry) != records.aware(payload.requested_expiry)
        ):
            raise HTTPException(
                409,
                {
                    "code": "idempotency_key_reuse",
                    "message": "The request changed; start a new request",
                },
            )
        return ConsentRequestOut(
            id=existing.id, status=existing.status, abha_address=existing.abha_address
        )
    try:
        row = await service.create_consent_request(
            db,
            facility_id=current_db_user.facility_id,
            patient_id=payload.patient_id,
            abha_address=payload.abha_address,
            purpose_code=payload.purpose_code,
            hi_types=payload.hi_types,
            date_range_from=payload.date_range_from,
            date_range_to=payload.date_range_to,
            requested_expiry=payload.requested_expiry,
            created_by=current_db_user.id,
            request_id=ident,
        )
    except service.HiuError as exc:
        raise _refusal(exc, status=400) from exc

    row.gateway_request_id = str(jobs.job_id("hiu_consent", row.id))
    await jobs.enqueue(db, kind="hiu_consent", target_id=row.id, facility_id=row.facility_id)

    return ConsentRequestOut(id=row.id, status=row.status, abha_address=row.abha_address)


class ArtefactOut(BaseModel):
    id: uuid.UUID
    consent_artefact_id: str
    status: str
    hi_types: list[str]
    expires_at: datetime | None


@router.get(
    "/consent-requests/{request_id}/artefacts",
    response_model=list[ArtefactOut],
    dependencies=[Depends(require_roles("doctor", "admin", "auditor"))],
)
async def list_artefacts(
    request_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: DbSession,
) -> list[ArtefactOut]:
    """The artefacts a request produced — the evidence for what we may hold."""
    rows = (
        (
            await db.execute(
                select(AbdmHiuConsentArtefact)
                .join(
                    AbdmConsentRequest,
                    AbdmConsentRequest.id == AbdmHiuConsentArtefact.consent_request_id,
                )
                .where(
                    AbdmHiuConsentArtefact.consent_request_id == request_id,
                    AbdmHiuConsentArtefact.facility_id == current_db_user.facility_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        ArtefactOut(
            id=r.id,
            consent_artefact_id=r.consent_artefact_id,
            status=r.status,
            hi_types=list(r.hi_types or []),
            expires_at=r.expires_at,
        )
        for r in rows
    ]


class HiRequestOut(BaseModel):
    id: uuid.UUID
    status: str
    key_material: dict


@router.post(
    "/artefacts/{artefact_id}/health-information",
    status_code=201,
    response_model=HiRequestOut,
    dependencies=[Depends(require_roles("doctor", "admin"))],
)
async def request_health_information(
    artefact_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    idempotency_key: IdempotencyKey,
    db: DbSession,
) -> HiRequestOut:
    """Mint key material and open a data request under a granted artefact.

    The returned `key_material` is the half that goes to the gateway. The
    private key stays in this database, encrypted — see the service docstring.
    """
    artefact = (
        await db.execute(
            select(AbdmHiuConsentArtefact)
            .join(
                AbdmConsentRequest,
                AbdmConsentRequest.id == AbdmHiuConsentArtefact.consent_request_id,
            )
            .where(
                AbdmHiuConsentArtefact.id == artefact_id,
                AbdmHiuConsentArtefact.facility_id == current_db_user.facility_id,
                AbdmConsentRequest.created_by == current_db_user.id,
            )
            .with_for_update(of=AbdmHiuConsentArtefact)
        )
    ).scalar_one_or_none()
    if artefact is None:
        # 404, not 403 — another facility's artefact must not be confirmable.
        raise HTTPException(404, {"code": "not_found", "message": "No such consent artefact"})

    ident = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"healthdoc:hiu-data:{current_db_user.facility_id}:{current_db_user.id}:{idempotency_key}",
    )
    existing = await db.get(AbdmHiuHealthInformationRequest, ident)
    if existing:
        if existing.artefact_id != artefact_id:
            raise HTTPException(
                409,
                {
                    "code": "idempotency_key_reuse",
                    "message": "The request changed; start a new request",
                },
            )
        return HiRequestOut(id=existing.id, status=existing.status, key_material={})
    try:
        row, wire = await service.begin_hi_request(
            db,
            facility_id=current_db_user.facility_id,
            artefact=artefact,
            created_by=current_db_user.id,
            request_id=ident,
        )
    except service.HiuError as exc:
        raise _refusal(exc, status=403) from exc

    # The artefact's range is nullable, and a null one means we do not know what
    # the manager actually permitted. Substituting the range we ASKED for would
    # be requesting records outside a consent we cannot evidence — the one thing
    # an HIU is judged on. Refuse instead.
    if artefact.date_range_from is None or artefact.date_range_to is None:
        raise HTTPException(
            409,
            {
                "code": "artefact_range_unknown",
                "message": (
                    "This consent artefact has no recorded date range, so the "
                    "permitted period is unknown. Re-fetch the artefact before "
                    "requesting records."
                ),
            },
        )

    try:
        await records.grant_for(db, row, now=datetime.now(UTC))
    except records.RecordRefused as exc:
        raise HTTPException(409, {"code": "consent_not_valid", "message": str(exc)}) from exc
    row.gateway_request_id = str(jobs.job_id("hiu_request", row.id))
    await jobs.enqueue(db, kind="hiu_request", target_id=row.id, facility_id=row.facility_id)

    return HiRequestOut(id=row.id, status=row.status, key_material=wire)


# =============================================================================
# Gateway / HIP callbacks — NO user, fail closed
# =============================================================================


class ReceivedRecordOut(BaseModel):
    id: uuid.UUID
    hi_type: str | None
    source_hip_id: str | None
    document_at: datetime | None
    status: str
    available: bool


class TransferStatusOut(BaseModel):
    id: uuid.UUID
    status: str
    delivery_status: str | None
    received_pages: int
    expected_pages: int | None
    records: list[ReceivedRecordOut]


class ConsentStatusOut(BaseModel):
    id: uuid.UUID
    status: str
    delivery_status: str | None
    hi_types: list[str]
    date_range_from: datetime
    date_range_to: datetime
    requested_expiry: datetime
    artefacts: list[ArtefactOut]
    transfers: list[TransferStatusOut]


class WorkspaceOut(BaseModel):
    patient_id: uuid.UUID
    patient_name: str
    abha_address: str | None
    identity_verified: bool
    requests: list[ConsentStatusOut]
    next_offset: int | None


@router.get(
    "/patients/{patient_id}/workspace",
    response_model=WorkspaceOut,
    dependencies=[Depends(require_roles("doctor"))],
)
async def patient_workspace(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> WorkspaceOut:
    patient = (
        await db.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.facility_id == current_db_user.facility_id,
                Patient.deleted_at.is_(None),
                Patient.merged_into_patient_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if patient is None:
        raise HTTPException(404, {"code": "not_found", "message": "Patient unavailable"})
    rows = list(
        (
            await db.execute(
                select(AbdmConsentRequest)
                .where(
                    AbdmConsentRequest.facility_id == current_db_user.facility_id,
                    AbdmConsentRequest.patient_id == patient_id,
                    AbdmConsentRequest.created_by == current_db_user.id,
                )
                .order_by(AbdmConsentRequest.created_at.desc(), AbdmConsentRequest.id)
                .limit(limit + 1)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    output = []
    now = datetime.now(UTC)
    for row in rows[:limit]:
        artefacts = list(
            (
                await db.execute(
                    select(AbdmHiuConsentArtefact).where(
                        AbdmHiuConsentArtefact.consent_request_id == row.id,
                        AbdmHiuConsentArtefact.facility_id == current_db_user.facility_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        transfers = list(
            (
                await db.execute(
                    select(AbdmHiuHealthInformationRequest)
                    .where(
                        AbdmHiuHealthInformationRequest.artefact_id.in_([a.id for a in artefacts]),
                        AbdmHiuHealthInformationRequest.facility_id == current_db_user.facility_id,
                    )
                    .order_by(AbdmHiuHealthInformationRequest.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        transfer_output = []
        for transfer in transfers:
            can_read = True
            try:
                await records.grant_for(db, transfer, now=now)
            except records.RecordRefused:
                can_read = False
            receipts = (
                (
                    await db.execute(
                        select(AbdmReceivedBundle)
                        .where(
                            AbdmReceivedBundle.hi_request_id == transfer.id,
                            AbdmReceivedBundle.facility_id == current_db_user.facility_id,
                        )
                        .order_by(AbdmReceivedBundle.page_number, AbdmReceivedBundle.entry_index)
                    )
                )
                .scalars()
                .all()
            )
            job = await db.get(jobs.AbdmJob, jobs.job_id("hiu_request", transfer.id))
            transfer_output.append(
                TransferStatusOut(
                    id=transfer.id,
                    status=transfer.status,
                    delivery_status=job.status if job else None,
                    received_pages=len(transfer.received_pages or []),
                    expected_pages=transfer.expected_page_count,
                    records=[
                        ReceivedRecordOut(
                            id=r.id,
                            hi_type=r.hi_type,
                            source_hip_id=r.source_hip_id,
                            document_at=r.document_at,
                            status=r.status,
                            available=can_read
                            and r.status == "stored"
                            and r.content_encrypted is not None
                            and r.erased_at is None,
                        )
                        for r in receipts
                    ],
                )
            )
        job = await db.get(jobs.AbdmJob, jobs.job_id("hiu_consent", row.id))
        output.append(
            ConsentStatusOut(
                id=row.id,
                status=row.status,
                delivery_status=job.status if job else None,
                hi_types=row.hi_types,
                date_range_from=row.date_range_from,
                date_range_to=row.date_range_to,
                requested_expiry=row.requested_expiry,
                artefacts=[
                    ArtefactOut(
                        id=a.id,
                        consent_artefact_id=a.consent_artefact_id,
                        status=a.status
                        if a.expires_at and records.aware(a.expires_at) > now
                        else "expired",
                        hi_types=a.hi_types,
                        expires_at=a.expires_at,
                    )
                    for a in artefacts
                ],
                transfers=transfer_output,
            )
        )
    return WorkspaceOut(
        patient_id=patient.id,
        patient_name=patient.full_name,
        abha_address=patient.abha_address,
        identity_verified=patient.abha_linked_at is not None and bool(patient.abha_address),
        requests=output,
        next_offset=offset + limit if len(rows) > limit else None,
    )


@router.get(
    "/records/{record_id}", response_model=dict, dependencies=[Depends(require_roles("doctor"))]
)
async def view_received_record(
    record_id: uuid.UUID, current_db_user: CurrentDbUser, db: DbSession, response: Response
) -> dict:
    try:
        bundle = await records.read_record(
            db, record_id, facility_id=current_db_user.facility_id, actor_id=current_db_user.id
        )
    except records.RecordRefused as exc:
        raise HTTPException(
            404,
            {
                "code": "record_unavailable",
                "message": "This external record is unavailable under your current consent",
            },
        ) from exc
    from app.audit.actions import AuditAction
    from app.audit.service import write_audit_log

    await write_audit_log(
        db,
        facility_id=current_db_user.facility_id,
        user_id=current_db_user.id,
        action=AuditAction.VIEW,
        resource_type="abdm_received_bundles",
        resource_id=record_id,
        reason="Consent-governed external record view",
    )
    response.headers["Cache-Control"] = "no-store, private"
    return bundle


class TransferIn(BaseModel):
    transaction_id: str
    care_context_reference: str | None = None
    ciphertext: str
    hip_public_key: str
    hip_nonce: str


@router.post(
    "/callbacks/health-information/transfer",
    status_code=202,
    dependencies=[Depends(verify_callback)],
)
async def receive_transfer(
    payload: TransferIn,
    db: DbSession,
) -> dict:
    """A HIP is pushing one encrypted bundle against a request we opened."""
    request = (
        await db.execute(
            select(AbdmHiuHealthInformationRequest).where(
                AbdmHiuHealthInformationRequest.transaction_id == payload.transaction_id
            )
        )
    ).scalar_one_or_none()
    if request is None:
        raise HTTPException(404, {"code": "unknown_transaction", "message": "Unknown transaction"})

    try:
        receipt = await service.receive_bundle(
            db,
            request=request,
            ciphertext_b64=payload.ciphertext,
            hip_public_key_b64=payload.hip_public_key,
            hip_nonce_b64=payload.hip_nonce,
            care_context_reference=payload.care_context_reference,
        )
    except service.HiuError as exc:
        # 422 rather than 500: the payload was well-formed HTTP and badly
        # formed cryptography, which is the sender's fault and is already
        # recorded against the request.
        raise _refusal(exc, status=422) from exc

    # External content stays in the encrypted consent-bound store.
    log.info("ABDM transfer accepted for request %s", request.id)
    return {"received": str(receipt.id), "status": receipt.status}

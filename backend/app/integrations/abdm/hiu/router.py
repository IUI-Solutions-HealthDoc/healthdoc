"""HIU (M3) endpoints.

Same two-kinds-of-route split as the HIP router, and the same rule: staff
routes take a bearer token and get their facility from it; gateway routes take
no user, depend on `verify_callback`, and refuse when this server has no shared
secret configured.

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
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.integrations.abdm.callback_auth import verify_callback
from app.integrations.abdm.hiu import service
from app.integrations.abdm.hiu.models import (
    AbdmConsentRequest,
    AbdmHiuConsentArtefact,
    AbdmHiuHealthInformationRequest,
)

log = logging.getLogger("healthdoc.abdm.hiu")

router = APIRouter(prefix="/abdm/hiu", tags=["abdm-hiu"])


def _refusal(exc: service.HiuError, status: int = 409) -> HTTPException:
    return HTTPException(status, {"code": exc.code, "message": exc.message})


def _require_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    """Mutations carry one. A retried consent request that opens a second ask
    is a second thing the patient has to answer."""
    if not idempotency_key:
        raise HTTPException(400, {
            "code": "idempotency_key_required",
            "message": "Idempotency-Key header is required for this request",
        })
    return idempotency_key


# =============================================================================
# Staff routes
# =============================================================================

class ConsentRequestIn(BaseModel):
    patient_id: uuid.UUID | None = None
    abha_address: str = Field(min_length=1, max_length=120)
    purpose_code: str
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
    idempotency_key: str = Depends(_require_idempotency_key),
    db: AsyncSession = Depends(get_db),
) -> ConsentRequestOut:
    """Ask the consent manager for access to a patient's records elsewhere."""
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
        )
    except service.HiuError as exc:
        raise _refusal(exc, status=400) from exc
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
    db: AsyncSession = Depends(get_db),
) -> list[ArtefactOut]:
    """The artefacts a request produced — the evidence for what we may hold."""
    rows = (
        await db.execute(
            select(AbdmHiuConsentArtefact)
            .join(AbdmConsentRequest, AbdmConsentRequest.id == AbdmHiuConsentArtefact.consent_request_id)
            .where(
                AbdmHiuConsentArtefact.consent_request_id == request_id,
                AbdmHiuConsentArtefact.facility_id == current_db_user.facility_id,
            )
        )
    ).scalars().all()
    return [
        ArtefactOut(id=r.id, consent_artefact_id=r.consent_artefact_id, status=r.status,
                    hi_types=list(r.hi_types or []), expires_at=r.expires_at)
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
    idempotency_key: str = Depends(_require_idempotency_key),
    db: AsyncSession = Depends(get_db),
) -> HiRequestOut:
    """Mint key material and open a data request under a granted artefact.

    The returned `key_material` is the half that goes to the gateway. The
    private key stays in this database, encrypted — see the service docstring.
    """
    artefact = (
        await db.execute(
            select(AbdmHiuConsentArtefact).where(
                AbdmHiuConsentArtefact.id == artefact_id,
                AbdmHiuConsentArtefact.facility_id == current_db_user.facility_id,
            )
        )
    ).scalar_one_or_none()
    if artefact is None:
        # 404, not 403 — another facility's artefact must not be confirmable.
        raise HTTPException(404, {"code": "not_found", "message": "No such consent artefact"})

    try:
        row, wire = await service.begin_hi_request(
            db, facility_id=current_db_user.facility_id,
            artefact=artefact, created_by=current_db_user.id,
        )
    except service.HiuError as exc:
        raise _refusal(exc, status=403) from exc

    return HiRequestOut(id=row.id, status=row.status, key_material=wire)


# =============================================================================
# Gateway / HIP callbacks — NO user, fail closed
# =============================================================================

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
    db: AsyncSession = Depends(get_db),
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
        receipt, plaintext = await service.receive_bundle(
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

    # The decrypted document does not go in the response, a log, or this table.
    # It goes to the outbox like every other clinical document; the receipt is
    # the durable fact that it arrived.
    log.info(
        "ABDM transfer accepted for request %s (%d bytes decrypted)",
        request.id, len(plaintext),
    )
    return {"received": str(receipt.id), "status": receipt.status}

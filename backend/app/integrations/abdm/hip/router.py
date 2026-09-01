"""HIP (M2) endpoints.

TWO KINDS OF ROUTE LIVE IN THIS FILE AND THEY ARE NOT THE SAME THING
--------------------------------------------------------------------
Staff routes are ordinary: a bearer token, `require_roles(...)`, and a facility
that comes from `CurrentDbUser` rather than the request body, exactly like the
rest of the app.

Gateway routes are the opposite and are grouped separately below so nobody
edits one thinking it is the other. They carry no user, they are reachable from
outside, and they create consent artefacts and move patient data. Every one of
them depends on `verify_callback`, which REFUSES when this server has no shared
secret configured. There is no development shortcut around that dependency; if
you are tempted to add one, read callback_auth.py's docstring first.

Facility attribution on inbound routes comes from `facilities.hfr_facility_id`
matched against the HIP id ABDM addressed. An unknown HFR id is refused — the
alternative is attributing another organisation's callback to whichever
facility happens to be first in the table.
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
from app.integrations.abdm.client import AbdmError
from app.integrations.abdm.hip import gateway, service
from app.integrations.abdm.hip.models import (
    AbdmCareContext,
    AbdmCareContextLink,
    AbdmHipHealthInformationRequest,
)
from app.users.models import Facility

log = logging.getLogger("healthdoc.abdm.hip")

router = APIRouter(prefix="/abdm/hip", tags=["abdm-hip"])


def _require_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    """Staff mutations carry one, per the house rule.

    Deliberately NOT applied to the gateway callbacks below. ABDM does not send
    our header — it identifies a retry by its own REQUEST-ID — so requiring it
    there would reject every real callback. Those two are made replay-safe by
    construction instead; see the note on each.
    """
    if not idempotency_key:
        raise HTTPException(400, {
            "code": "idempotency_key_required",
            "message": "Idempotency-Key header is required for this request",
        })
    return idempotency_key


async def _acknowledge(what: str, coro) -> None:
    """Send an acknowledgement the gateway is waiting for, and never fail on it.

    These run AFTER the notification is durably recorded, and the callback has
    already promised the gateway 202. Raising here would turn a recorded
    notification into a 500, and the gateway would redeliver something we
    already hold.

    Not acknowledging is not free either — the gateway retries and then treats
    the grant or request as failed, so the patient's consent silently does not
    take effect. That is why this is logged at ERROR rather than swallowed: it
    needs someone to look, but not at the cost of the record we just wrote.
    """
    try:
        await coro
    except gateway.HipIdentityNotConfigured as exc:
        log.error("Could not acknowledge %s — %s", what, exc)
    except AbdmError as exc:
        log.error("Could not acknowledge %s to ABDM (%s)", what, type(exc).__name__)


def _refusal(exc: service.HipError, status: int = 409) -> HTTPException:
    return HTTPException(status, {"code": exc.code, "message": exc.message})


async def _facility_for_hfr_id(db: AsyncSession, hfr_id: str) -> uuid.UUID:
    facility = (
        await db.execute(select(Facility).where(Facility.hfr_facility_id == hfr_id))
    ).scalar_one_or_none()
    if facility is None:
        # 404 rather than 403, the same rule the rest of this codebase follows
        # for a record that is not yours: a 403 would confirm which HFR ids
        # this deployment serves.
        log.warning("ABDM callback for an HFR id this deployment does not serve")
        raise HTTPException(404, {"code": "unknown_hip", "message": "Unknown HIP"})
    return facility.id


# =============================================================================
# Staff routes — bearer token, role-gated, facility from the token
# =============================================================================

class CareContextIn(BaseModel):
    patient_id: uuid.UUID
    visit_id: uuid.UUID | None = None
    reference: str = Field(min_length=1, max_length=100)
    display: str = Field(min_length=1, max_length=200)
    hi_type: str


class CareContextOut(BaseModel):
    id: uuid.UUID
    reference: str
    display: str
    hi_type: str


@router.post(
    "/care-contexts",
    status_code=201,
    response_model=CareContextOut,
    dependencies=[Depends(require_roles("doctor", "receptionist", "admin"))],
)
async def create_care_context(
    payload: CareContextIn,
    current_db_user: CurrentDbUser,
    idempotency_key: str = Depends(_require_idempotency_key),
    db: AsyncSession = Depends(get_db),
) -> CareContextOut:
    """Register a unit of care as offerable to an ABHA address.

    Creating the context does not share anything. Sharing needs a confirmed
    link AND a consent artefact — see service.authorise_hi_request.
    """
    context = AbdmCareContext(
        facility_id=current_db_user.facility_id,
        patient_id=payload.patient_id,
        visit_id=payload.visit_id,
        reference=payload.reference,
        display=payload.display,
        hi_type=payload.hi_type,
        created_by=current_db_user.id,
    )
    db.add(context)
    await db.flush()
    return CareContextOut(
        id=context.id, reference=context.reference,
        display=context.display, hi_type=context.hi_type,
    )


@router.post(
    "/care-contexts/{context_id}/notify",
    status_code=202,
    dependencies=[Depends(require_roles("doctor", "receptionist", "admin"))],
)
async def notify_care_context(
    context_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    idempotency_key: str = Depends(_require_idempotency_key),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Tell the consent manager a new care context exists for a linked patient.

    This is the step whose absence is the classic HIP defect: linking works
    once, and every record created afterwards is invisible to the patient
    because the CM was never told it exists.

    Requires a CONFIRMED link. Notifying against a pending link tells the CM
    about a care context belonging to an ABHA address that has not yet proved
    it owns this patient's records.
    """
    context = (
        await db.execute(
            select(AbdmCareContext).where(
                AbdmCareContext.id == context_id,
                AbdmCareContext.facility_id == current_db_user.facility_id,
            )
        )
    ).scalar_one_or_none()
    if context is None:
        # 404 not 403, the same rule as everywhere else here.
        raise HTTPException(404, {"code": "not_found", "message": "No such care context"})

    link = (
        await db.execute(
            select(AbdmCareContextLink).where(
                AbdmCareContextLink.patient_id == context.patient_id,
                AbdmCareContextLink.facility_id == current_db_user.facility_id,
                AbdmCareContextLink.status == "confirmed",
            )
        )
    ).scalars().first()
    if link is None:
        raise HTTPException(409, {
            "code": "not_linked",
            "message": (
                "This patient has no confirmed ABHA link, so there is nobody to "
                "notify. Link the patient before sharing new care contexts."
            ),
        })

    try:
        request_id, _ = await gateway.notify_care_context(
            abha_address=link.abha_address,
            care_context_reference=context.reference,
            hi_types=[context.hi_type],
        )
    except gateway.HipIdentityNotConfigured as exc:
        raise HTTPException(503, {"code": "abdm_not_configured", "message": str(exc)}) from exc
    except AbdmError as exc:
        # Type only. The gateway's body echoes the ABHA address we just sent.
        log.error("Care-context notification failed (%s)", type(exc).__name__)
        raise HTTPException(502, {
            "code": "abdm_unavailable",
            "message": "ABDM did not accept the notification. Nothing was shared.",
        }) from exc

    return {"notified": context.reference, "request_id": request_id}


class LinkOut(BaseModel):
    id: uuid.UUID
    abha_address: str
    status: str
    failure_reason: str | None


@router.get(
    "/patients/{patient_id}/links",
    response_model=list[LinkOut],
    dependencies=[Depends(require_roles("doctor", "receptionist", "admin"))],
)
async def list_links(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> list[LinkOut]:
    """Which ABHA addresses may see this patient's records here."""
    rows = (
        await db.execute(
            select(AbdmCareContextLink).where(
                AbdmCareContextLink.patient_id == patient_id,
                # Scoped by the token's facility, never the path.
                AbdmCareContextLink.facility_id == current_db_user.facility_id,
            )
        )
    ).scalars().all()
    return [
        LinkOut(id=r.id, abha_address=r.abha_address, status=r.status,
                failure_reason=r.failure_reason)
        for r in rows
    ]


# =============================================================================
# Gateway callbacks — NO user, authenticated by shared secret, fail closed
# =============================================================================

class ConsentNotification(BaseModel):
    hip_id: str
    consent_artefact_id: str
    abha_address: str
    status: str
    hi_types: list[str] = Field(default_factory=list)
    date_range_from: datetime | None = None
    date_range_to: datetime | None = None
    expires_at: datetime | None = None
    #: The gateway's own REQUEST-ID for this notification. It goes back in
    #: `response.requestId` on the acknowledgement and is the only thing that
    #: correlates our answer to its question. Optional because the notification
    #: is still worth RECORDING without it — losing a consent grant because we
    #: could not acknowledge it would be the worse failure — but without it no
    #: acknowledgement can be sent, so its absence is logged where it happens.
    gateway_request_id: str | None = None
    raw: dict = Field(default_factory=dict)


@router.post(
    "/callbacks/consent-notify",
    status_code=202,
    dependencies=[Depends(verify_callback)],
)
async def consent_notify(
    payload: ConsentNotification,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The consent manager tells us a consent was granted, revoked or expired.

    202, not 200: we have durably recorded the notification, which is all the
    gateway needs to stop retrying. Acting on it is our business.

    Replay-safe without an Idempotency-Key: consent_artefact_id is UNIQUE and
    record_consent_notification() upserts on it, so a repeated notification
    updates the row it already wrote rather than creating a second one. The one
    replay it refuses is granted-after-revoked, which is not a retry — ABDM
    issues a new artefact on re-grant, so that shape is a stale message and
    honouring it would undo a revocation.
    """
    facility_id = await _facility_for_hfr_id(db, payload.hip_id)
    try:
        artefact = await service.record_consent_notification(
            db,
            facility_id=facility_id,
            artefact_id=payload.consent_artefact_id,
            abha_address=payload.abha_address,
            status=payload.status,
            hi_types=payload.hi_types,
            date_range_from=payload.date_range_from,
            date_range_to=payload.date_range_to,
            expires_at=payload.expires_at,
            raw=payload.raw or payload.model_dump(mode="json"),
        )
    except service.HipError as exc:
        raise _refusal(exc) from exc

    # Until this existed the notification was recorded and never acknowledged,
    # so the gateway retried and then marked the grant failed — the consent took
    # effect here and nowhere else.
    if payload.gateway_request_id:
        await _acknowledge(
            "consent notification",
            gateway.acknowledge_consent_notification(
                consent_id=payload.consent_artefact_id,
                gateway_request_id=payload.gateway_request_id,
            ),
        )
    else:
        log.error(
            "Consent notification carried no gateway request id — recorded, but "
            "it cannot be acknowledged and the gateway will retry then fail it."
        )

    return {"recorded": str(artefact.id), "status": artefact.status}


class HiRequestIn(BaseModel):
    hip_id: str
    transaction_id: str
    consent_artefact_id: str
    abha_address: str
    hi_types: list[str]
    date_range_from: datetime | None = None
    date_range_to: datetime | None = None
    data_push_url: str
    key_material: dict
    gateway_request_id: str | None = None


@router.post(
    "/callbacks/health-information/request",
    status_code=202,
    dependencies=[Depends(verify_callback)],
)
async def hi_request(
    payload: HiRequestIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """A HIU is asking for data under a consent artefact.

    Authorised BEFORE anything is recorded as transferable, and refused with a
    named reason when the artefact does not cover the ask. The refusal is
    persisted too: "we declined and why" is as much a part of the trail as a
    successful release.
    """
    facility_id = await _facility_for_hfr_id(db, payload.hip_id)

    # Replay safety without our Idempotency-Key header. transaction_id is
    # UNIQUE, so a gateway retry would otherwise hit an integrity error and
    # come back as a 500 — which the gateway reads as "try again", producing a
    # retry loop against a request we already accepted. Answering with the
    # recorded outcome is both correct and what stops the loop.
    already = (
        await db.execute(
            select(AbdmHipHealthInformationRequest).where(
                AbdmHipHealthInformationRequest.transaction_id == payload.transaction_id
            )
        )
    ).scalar_one_or_none()
    if already is not None:
        if already.status == "refused":
            raise HTTPException(403, {
                "code": already.failure_reason or "consent_not_valid",
                "message": "This request was already refused",
            })
        return {
            "accepted": already.transaction_id,
            "care_contexts": int(already.bundles_sent or 0),
            "replayed": True,
        }

    try:
        authorisation = await service.authorise_hi_request(
            db,
            facility_id=facility_id,
            consent_artefact_id=payload.consent_artefact_id,
            requested_hi_types=payload.hi_types,
            requested_from=payload.date_range_from,
            requested_to=payload.date_range_to,
        )
    except service.HipError as exc:
        row = await service.record_hi_request(
            db,
            facility_id=facility_id,
            transaction_id=payload.transaction_id,
            consent_artefact_id=payload.consent_artefact_id,
            hiu_key_material=payload.key_material,
            data_push_url=payload.data_push_url,
            gateway_request_id=payload.gateway_request_id,
        )
        row.status = "refused"
        row.failure_reason = exc.code
        await db.flush()
        raise _refusal(exc, status=403) from exc

    row = await service.record_hi_request(
        db,
        facility_id=facility_id,
        transaction_id=payload.transaction_id,
        consent_artefact_id=payload.consent_artefact_id,
        hiu_key_material=payload.key_material,
        data_push_url=payload.data_push_url,
        gateway_request_id=payload.gateway_request_id,
    )

    contexts = await service.list_care_contexts_for_transfer(
        db,
        facility_id=facility_id,
        abha_address=payload.abha_address,
        authorisation=authorisation,
    )
    row.bundles_sent = str(len(contexts))
    await db.flush()

    # ACKNOWLEDGED tells the gateway we accepted the request and will transfer
    # out of band. Without it the gateway retries the request and then reports
    # the session failed to the patient, even though we authorised it and hold
    # the records ready.
    if payload.gateway_request_id:
        await _acknowledge(
            "health-information request",
            gateway.acknowledge_hi_request(
                transaction_id=payload.transaction_id,
                gateway_request_id=payload.gateway_request_id,
            ),
        )
    else:
        log.error(
            "Health-information request carried no gateway request id — "
            "authorised and recorded, but it cannot be acknowledged."
        )

    # The push itself is not done inline. It is an outbound HTTP call to a URL
    # the gateway supplied, and doing it inside this request would hold the
    # gateway's connection open for as long as it takes — the exact shape of
    # the SSE/buffering problem already documented in infra/nginx. The transfer
    # worker picks these up; this endpoint's job is to accept, authorise and
    # record.
    return {
        "accepted": row.transaction_id,
        "care_contexts": len(contexts),
        "hi_types": authorisation.hi_types,
    }

"""ABHA capture endpoint (B1-W6-01).

Captures/links an ABHA to a patient: verifies with the ABDM gateway (graceful
degradation if unreachable), stores the returned linking token ENCRYPTED
(key-versioned, common/security.py), and enqueues an outbox event so the link
syncs to the cloud. Never stores the token in plaintext.

Follows the same graceful-degradation pattern as integrations/icd11/client.py:
a rural facility going offline must not break registration.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.config import get_settings
from app.common.db import get_db
from app.common.security import current_aes_key_version, encrypt_pii
from app.integrations.abdm.client import (
    AbdmAuthError,
    AbdmNotConfigured,
    AbdmRejected,
    AbdmUnavailable,
    get_abdm_client,
)
from app.integrations.abdm.identity import otp_session
from app.integrations.abdm.identity import service as identity_service
from app.integrations.abdm.identity.crypto import AbdmPublicKeyMissing
from app.integrations.abdm.identity.formatting import hyphenate_abha
from app.integrations.abdm.identity.otp_session import (
    OtpPurpose,
    OtpSessionMismatch,
    OtpSessionNotFound,
)
from app.outbox.service import enqueue
from app.patients.models import Patient

log = logging.getLogger("healthdoc.abdm")
router = APIRouter(prefix="/abdm/abha", tags=["abdm"])
DbSession = Annotated[AsyncSession, Depends(get_db)]

#: The ABDM v3 path that verifies an ABHA number, relative to
#: `abdm_abha_base_url` — NOT the gateway base. Confirmed against the sandbox
#: on 2026-09-01; the same path on the gateway base answers 503.
#:
#: It held None for months rather than a guess, because the previous value was
#: `/v3/hip/token/on-generate` — a callback the gateway invokes ON a HIP, not
#: something a HIP posts to. A plausible constant is worse than an absent one.
#:
#: Three things about this endpoint are not guessable and each fails quietly if
#: got wrong, so all three are pinned by tests:
#:   * the body key is `ABHANumber`, capitalised. `abhaNumber` returns
#:     400 "Invalid ABHA Number", which reads like bad input, not a bad key.
#:   * the value must be HYPHENATED (91-0000-0000-0001). We store the number
#:     stripped, so it has to be re-formatted on the way out; the stripped form
#:     also returns 400 "Invalid ABHA Number".
#:   * an absent ABHA is 404 with code ABDM-1114 "User not found" — a real
#:     answer, not a transport failure, and it must not be logged as an outage.
_VERIFY_PATH: str | None = "/v3/profile/login/search"

#: ABDM's "this ABHA does not exist" answer. Distinct from a gateway outage.
_ABHA_NOT_FOUND_CODE = "ABDM-1114"


async def _verify_with_gateway(abha_number: str) -> dict | None:
    """Verify an ABHA with the gateway. None means "not verified".

    WHAT THIS USED TO DO, AND WHY IT MATTERS
    ----------------------------------------
    This built its own httpx call and sent `abdm_client_secret` in an
    `Authorization: Bearer` header. The client secret is what you EXCHANGE for a
    session token; it is not one. Every such call 401s — so ABHA verification had
    never once succeeded, against the sandbox or anything else.

    Nobody noticed because the old error handling ended in a bare
    `except Exception: return None` that logged "proceeding offline". A
    permanently broken integration and a facility with no internet produced
    identical logs and identical behaviour. That is the whole lesson here:
    graceful degradation that cannot distinguish "down" from "wrong" is not
    resilience, it is a silencer.

    It failed CLOSED, which is the one piece of luck — `gateway_verified` was
    always False, so the caller marked patients `identity_unverified` rather
    than falsely verified. No bad data was written. The cost was a dead feature
    and a client secret on the wire in a form that could never authenticate.

    WHAT IT DOES NOW
    ----------------
    Goes through `AbdmClient`, which is the only thing in this codebase allowed
    to talk to the gateway: it obtains a real session token, caches it, sends
    REQUEST-ID / TIMESTAMP / X-CM-ID, and raises a typed error per failure mode.

    Three outcomes are now distinguishable in the logs, where before there was
    one: not configured, gateway unavailable, and gateway said no.

    `_VERIFY_PATH` is pinned to the sandbox endpoint and contract-tested. A
    transport outage still records the number as unverified; the OTP flows
    below are the path that can produce a verified patient identity.
    """
    # Ordered most-certain-first: an unknown path and absent credentials are
    # both facts we hold locally, and neither should reach the network.
    if _VERIFY_PATH is None:
        log.info(
            "ABDM verify path not yet set from the v3 spec — "
            "ABHA recorded without gateway verification"
        )
        return None

    client = get_abdm_client()

    # Unconfigured is not a failure, and must not put a placeholder secret on
    # the wire. Checked here rather than caught as AbdmNotConfigured so the
    # request is never built at all.
    if not client.is_configured:
        log.info("ABDM not configured — ABHA recorded without gateway verification")
        return None

    try:
        response = await client.request(
            "POST",
            # Absolute URL: enrolment and verification live on the ABHA host,
            # while the client's base is the gateway. Same pattern as
            # identity/service.py.
            f"{get_settings().abdm_abha_base_url.rstrip('/')}{_VERIFY_PATH}",
            json={"ABHANumber": hyphenate_abha(abha_number)},
        )
    except AbdmNotConfigured:
        log.info("ABDM not configured — ABHA recorded without gateway verification")
        return None
    except AbdmUnavailable:
        # The genuine offline case this endpoint's degradation was written for.
        log.warning("ABDM gateway unavailable — ABHA recorded unverified")
        return None
    except AbdmAuthError:
        # Ours to fix, not the network's. Logged at ERROR so it stops hiding
        # inside the offline case the way the old code let it.
        log.error("ABDM rejected our credentials — ABHA verification is DOWN, not offline")
        return None
    except AbdmRejected as exc:
        # 404 ABDM-1114 is ABDM saying "no such ABHA" — a successful lookup with
        # a negative result. Logged apart from a decline so an unverifiable
        # number is not read as an integration fault. Status and error code
        # only; the body can carry PHI.
        if exc.status_code == 404:
            log.info("ABDM: no such ABHA (%s) — recorded unverified", _ABHA_NOT_FOUND_CODE)
        else:
            log.warning("ABDM declined ABHA verification (%s)", exc.status_code)
        return None

    body = response.body
    # A 2xx whose body is not an object is not a verification. Returning it
    # would make `gateway_result is not None` true on a bare `null` or `""`.
    if not isinstance(body, dict):
        log.warning(
            "ABDM returned %s with a non-object body — treating as unverified", response.status_code
        )
        return None
    return body


class AbhaOut(BaseModel):
    patient_id: uuid.UUID
    abha_number: str | None

    model_config = {"from_attributes": True}


def _normalise_abha(raw: str) -> str:
    """ABHA numbers are quoted with or without hyphens; store one form."""
    return raw.replace("-", "").strip()


async def _get_patient_or_404(
    db: AsyncSession, patient_id: uuid.UUID, facility_id: uuid.UUID
) -> Patient:
    """404 rather than 403 for another facility's patient — a 403 confirms the
    row exists, which is enough to probe for patients across facilities."""
    patient = await db.get(Patient, patient_id)
    if patient is None or patient.facility_id != facility_id:
        raise HTTPException(404, {"code": "patient_not_found"})
    return patient


@router.get(
    "/patients/{patient_id}/abha",
    response_model=AbhaOut,
    dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "admin"))],
)
async def get_abha(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: DbSession,
) -> AbhaOut:
    """Read a patient's linked ABHA. Facility-scoped via _get_patient_or_404."""
    patient = await _get_patient_or_404(db, patient_id, current_db_user.facility_id)
    return AbhaOut(patient_id=patient.id, abha_number=patient.abha_number)


@router.delete(
    "/patients/{patient_id}/abha",
    response_model=AbhaOut,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def unlink_abha(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: DbSession,
) -> AbhaOut:
    """Unlink an ABHA, clearing the encrypted token with it.

    All three columns go together. Clearing abha_number alone would leave
    abha_linking_token_encrypted and abha_linking_key_version populated — an
    encrypted ABDM token for a link that no longer exists, which is the exact
    half-record state 0030's both-or-neither CHECK exists to prevent, and a
    DPDP problem besides: we would be retaining an identity credential after
    the relationship it belonged to was severed.
    """
    patient = await _get_patient_or_404(db, patient_id, current_db_user.facility_id)

    if patient.abha_number is None:
        raise HTTPException(
            409,
            {
                "code": "no_abha_linked",
                "message": "Patient has no ABHA number linked",
            },
        )

    patient.abha_number = None
    patient.abha_address = None
    patient.abha_linking_token_encrypted = None
    patient.abha_linking_key_version = None
    patient.abha_linked_at = None
    patient.updated_by = current_db_user.id
    await db.flush()

    await enqueue(
        db,
        aggregate_type="patient",
        aggregate_id=str(patient.id),
        event_type="abha_unlinked",
        payload={},
        sensitivity="important",
    )
    await db.refresh(patient)
    return AbhaOut(patient_id=patient.id, abha_number=None)


# ---------------------------------------------------------------- M1 flows
#
# Creating an ABHA (Aadhaar + OTP) and proving an existing one (ABHA + OTP).
# Both are two-legged: request, then verify. Our session id is what the client
# holds between the legs — ABDM's transaction id never leaves the server,
# because a client holding it could replay it against ABDM directly.
#
# Gated to the desk that actually registers patients. Not admin: an
# administrator is not the person with the patient in front of them, and an
# identity flow completed by someone who never met them is exactly the
# attribution gap this codebase has fixed three times elsewhere.


class AadhaarOtpRequest(BaseModel):
    #: Twelve digits. Encrypted before transmission and never stored.
    aadhaar: str = Field(min_length=12, max_length=12, pattern=r"^\d{12}$")
    patient_id: uuid.UUID


class AbhaLoginOtpRequest(BaseModel):
    """Exactly one identifier: the ABHA number (OTP to the ABHA-linked mobile)
    or the Aadhaar number (OTP through Aadhaar, workbook VRFY_ABHA_101/401)."""

    abha_number: str | None = None
    #: Twelve digits. Encrypted before transmission and never stored.
    aadhaar: str | None = Field(default=None, min_length=12, max_length=12, pattern=r"^\d{12}$")
    patient_id: uuid.UUID

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> "AbhaLoginOtpRequest":
        if (self.abha_number is None) == (self.aadhaar is None):
            raise ValueError("provide exactly one of abha_number or aadhaar")
        return self


class OtpResendRequest(BaseModel):
    """Ask for a fresh OTP within the same desk attempt. The identifier is
    re-supplied because the session never stored it."""

    session_id: str
    patient_id: uuid.UUID
    abha_number: str | None = None
    aadhaar: str | None = Field(default=None, min_length=12, max_length=12, pattern=r"^\d{12}$")

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> "OtpResendRequest":
        if (self.abha_number is None) == (self.aadhaar is None):
            raise ValueError("provide exactly one of abha_number or aadhaar")
        return self


class OtpVerifyRequest(BaseModel):
    session_id: str
    otp: str = Field(min_length=4, max_length=8, pattern=r"^\d{4,8}$")
    #: Enrolment only — the mobile to attach to the new ABHA.
    mobile: str | None = Field(default=None, pattern=r"^\d{10}$")


class OtpRequestedOut(BaseModel):
    session_id: str
    masked_mobile: str | None = None
    #: Fresh OTP requests still available for this desk attempt.
    resends_remaining: int = otp_session.MAX_RESENDS


class AbhaIssuedOut(BaseModel):
    abha_number: str
    abha_address: str | None = None
    name: str | None = None
    gender: str | None = None
    date_of_birth: str | None = None
    linked_patient_id: uuid.UUID
    linked: bool = True
    #: Deliberately absent: the linking token. It is a credential, it is stored
    #: encrypted server-side by the link endpoint, and a browser has no use for
    #: it. Returning it would put it in a response body, a proxy log and a
    #: React devtools tree for no gain.


def _identity_error(exc: identity_service.AbdmIdentityError) -> HTTPException:
    # Identifier-shape refusals are the caller's to correct; everything else is
    # the gateway conversation going wrong.
    status = 400 if exc.code == "abdm_identifier_required" else 502
    return HTTPException(status, {"code": exc.code, "message": exc.message})


def _otp_rejected(exc: AbdmRejected, leg: str) -> HTTPException:
    """A gateway 4xx on the verify leg is a correctable refusal (wrong, expired
    or over-tried OTP; workbook VRFY_ABHA_304/402), not a gateway outage. The
    session stays alive so the desk can retry or request a fresh OTP. Status
    only is logged: the body can echo the OTP or identifier just sent."""
    log.warning("ABDM declined a %s verification (%s)", leg, exc.status_code)
    return HTTPException(
        400,
        {
            "code": "otp_rejected",
            "message": "ABDM did not accept this OTP. It may be wrong, expired or "
            "over the attempt limit. Check the code and try again, or request a new OTP.",
        },
    )


async def _resend(
    payload: OtpResendRequest,
    current_db_user: CurrentDbUser,
    db: AsyncSession,
    purpose: OtpPurpose,
) -> OtpRequestedOut:
    session = await _bound_otp_session(db, current_db_user, payload.session_id, purpose)
    if session.patient_id != str(payload.patient_id):
        raise HTTPException(
            404,
            {"code": "otp_session_not_found", "message": "This OTP session has expired or does not exist"},
        )
    try:
        result = await identity_service.resend_otp(
            session_id=payload.session_id,
            purpose=purpose,
            facility_id=str(current_db_user.facility_id),
            started_by=str(current_db_user.id),
            abha_number=_normalise_abha(payload.abha_number) if payload.abha_number else None,
            aadhaar=payload.aadhaar,
        )
    except (OtpSessionNotFound, OtpSessionMismatch):
        raise HTTPException(
            404,
            {"code": "otp_session_not_found", "message": "This OTP session has expired or does not exist"},
        ) from None
    except otp_session.OtpResendTooSoon as exc:
        raise HTTPException(
            429,
            {
                "code": "otp_resend_too_soon",
                "message": f"Wait {exc.retry_after_seconds} seconds before requesting another OTP",
                "retry_after_seconds": exc.retry_after_seconds,
            },
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except otp_session.OtpResendExhausted:
        raise HTTPException(
            429,
            {
                "code": "otp_resend_exhausted",
                "message": "No more OTP resends for this attempt. Start the verification again.",
            },
        ) from None
    except AbdmNotConfigured:
        raise _unavailable("ABDM credentials are not configured on this server") from None
    except AbdmPublicKeyMissing:
        raise _unavailable("ABDM public certificate is not configured on this server") from None
    except AbdmUnavailable:
        raise _unavailable("ABDM did not respond") from None
    except AbdmRejected as exc:
        log.warning("ABDM declined an OTP resend (%s)", exc.status_code)
        raise HTTPException(502, {"code": "abdm_rejected", "message": "ABDM declined the request"}) from exc
    except identity_service.AbdmIdentityError as exc:
        raise _identity_error(exc) from exc
    return OtpRequestedOut(
        session_id=result.session_id,
        masked_mobile=result.masked_mobile,
        resends_remaining=result.resends_remaining,
    )


def _unavailable(reason: str) -> HTTPException:
    return HTTPException(503, {"code": "abdm_unavailable", "message": reason})


async def _persist_verified_identity(
    *,
    db: AsyncSession,
    current_db_user: CurrentDbUser,
    session_id: str,
    purpose: OtpPurpose,
    issued: identity_service.AbhaIssued,
) -> uuid.UUID:
    """Bind a successful OTP result without ever exposing its token to a client."""
    session = await _bound_otp_session(db, current_db_user, session_id, purpose)
    if not issued.linking_token:
        raise HTTPException(
            502,
            {
                "code": "abdm_no_linking_token",
                "message": "ABDM verified the identity but returned no linking credential",
            },
        )

    patient_id = uuid.UUID(session.patient_id)
    patient = await _get_patient_or_404(db, patient_id, current_db_user.facility_id)
    normalised = _normalise_abha(issued.abha_number)
    clash = (
        await db.execute(
            select(Patient.id).where(
                Patient.abha_number == normalised,
                Patient.id != patient.id,
            )
        )
    ).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(
            409,
            {
                "code": "duplicate_abha",
                "message": "This ABHA number is already linked to another patient",
            },
        )

    key_version = current_aes_key_version()
    patient.abha_number = normalised
    patient.abha_address = issued.abha_address
    patient.abha_linking_token_encrypted = encrypt_pii(
        issued.linking_token, key_version=key_version
    )
    patient.abha_linking_key_version = key_version
    patient.abha_linked_at = datetime.now(UTC)
    patient.identity_status = "verified"
    patient.updated_by = current_db_user.id
    await db.flush()
    await enqueue(
        db,
        aggregate_type="patient",
        aggregate_id=str(patient.id),
        event_type="abha_linked",
        payload={"abha_number": normalised},
        sensitivity="important",
    )
    # Consume proof only after the identity and its event are durable. A failed
    # database commit must not destroy the patient's successful OTP session.
    await db.commit()
    try:
        await otp_session.finish(session_id)
    except Exception:
        # Redis still expires this session; do not tell the desk a committed
        # identity write failed. Never log the credential or transaction id.
        log.error("ABHA identity committed; OTP session cleanup failed")
    return patient.id


async def _bound_otp_session(
    db: AsyncSession, actor: CurrentDbUser, session_id: str, purpose: OtpPurpose
) -> otp_session.OtpSession:
    refusal = HTTPException(
        404,
        {
            "code": "otp_session_not_found",
            "message": "This OTP session has expired or does not exist",
        },
    )
    try:
        session = await otp_session.load(
            session_id, facility_id=str(actor.facility_id), purpose=purpose
        )
    except (OtpSessionNotFound, OtpSessionMismatch) as exc:
        raise refusal from exc
    if session.started_by != str(actor.id) or not session.patient_id:
        raise refusal
    try:
        patient_id = uuid.UUID(session.patient_id)
    except ValueError as exc:
        raise refusal from exc
    patient = (
        await db.execute(
            select(Patient)
            .where(
                Patient.id == patient_id,
                Patient.facility_id == actor.facility_id,
                Patient.deleted_at.is_(None),
                Patient.merged_into_patient_id.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if patient is None:
        raise refusal
    return session


@router.post(
    "/enrol/aadhaar/request-otp",
    response_model=OtpRequestedOut,
    dependencies=[Depends(require_roles("receptionist", "doctor"))],
)
async def enrol_request_otp(
    payload: AadhaarOtpRequest,
    current_db_user: CurrentDbUser,
    db: DbSession,
) -> OtpRequestedOut:
    """Send an OTP to the mobile registered against this Aadhaar.

    The Aadhaar number is encrypted in this call and referenced nowhere after
    it — not in the OTP session, not in an audit row, not in a log line.
    """
    await _get_patient_or_404(db, payload.patient_id, current_db_user.facility_id)
    try:
        result = await identity_service.request_aadhaar_otp(
            aadhaar=payload.aadhaar,
            facility_id=str(current_db_user.facility_id),
            started_by=str(current_db_user.id),
            patient_id=str(payload.patient_id),
        )
    except AbdmNotConfigured:
        raise _unavailable("ABDM credentials are not configured on this server") from None
    except AbdmPublicKeyMissing:
        raise _unavailable("ABDM public certificate is not configured on this server") from None
    except AbdmUnavailable:
        raise _unavailable("ABDM did not respond") from None
    except AbdmRejected as exc:
        # Status only. The gateway's body can echo the identifier we just sent.
        log.warning("ABDM declined an enrolment OTP request (%s)", exc.status_code)
        raise HTTPException(
            502,
            {
                "code": "abdm_rejected",
                "message": "ABDM declined the request",
            },
        ) from exc
    except identity_service.AbdmIdentityError as exc:
        raise _identity_error(exc) from exc

    return OtpRequestedOut(
        session_id=result.session_id,
        masked_mobile=result.masked_mobile,
        resends_remaining=result.resends_remaining,
    )


@router.post(
    "/enrol/aadhaar/resend-otp",
    response_model=OtpRequestedOut,
    dependencies=[Depends(require_roles("receptionist", "doctor"))],
)
async def enrol_resend_otp(
    payload: OtpResendRequest,
    current_db_user: CurrentDbUser,
    db: DbSession,
) -> OtpRequestedOut:
    """Fresh enrolment OTP for the same patient and desk attempt (CRT_ABHA_106).

    Cooldown and a resend limit are enforced server-side; the previous session
    is consumed only once ABDM accepted the new request.
    """
    if payload.aadhaar is None:
        raise HTTPException(400, {"code": "abdm_identifier_required", "message": "Enrolment resend requires the Aadhaar number"})
    await _get_patient_or_404(db, payload.patient_id, current_db_user.facility_id)
    return await _resend(payload, current_db_user, db, OtpPurpose.ENROL_BY_AADHAAR)


@router.post(
    "/enrol/aadhaar/verify-otp",
    response_model=AbhaIssuedOut,
    dependencies=[Depends(require_roles("receptionist", "doctor"))],
)
async def enrol_verify_otp(
    payload: OtpVerifyRequest,
    current_db_user: CurrentDbUser,
    db: DbSession,
) -> AbhaIssuedOut:
    """Present the OTP and receive a newly created ABHA."""
    try:
        # Check ownership BEFORE spending an OTP at the gateway, not only
        # after it has already been consumed by a different staff account.
        await _bound_otp_session(
            db, current_db_user, payload.session_id, OtpPurpose.ENROL_BY_AADHAAR
        )
        issued = await identity_service.enrol_by_aadhaar_otp(
            session_id=payload.session_id,
            otp=payload.otp,
            mobile=payload.mobile,
            facility_id=str(current_db_user.facility_id),
            consume_session=False,
        )
    except (OtpSessionNotFound, OtpSessionMismatch):
        # One response for expired, already-spent, wrong-facility and
        # wrong-purpose. Distinguishing them would confirm that someone else's
        # transaction exists, which is the enumeration oracle this codebase
        # avoids with 404-not-403 everywhere else.
        raise HTTPException(
            404,
            {
                "code": "otp_session_not_found",
                "message": "This OTP session has expired or does not exist",
            },
        ) from None
    except AbdmNotConfigured:
        raise _unavailable("ABDM credentials are not configured on this server") from None
    except AbdmPublicKeyMissing:
        raise _unavailable("ABDM public certificate is not configured on this server") from None
    except AbdmUnavailable:
        raise _unavailable("ABDM did not respond") from None
    except AbdmRejected as exc:
        raise _otp_rejected(exc, "enrolment") from exc
    except identity_service.AbdmIdentityError as exc:
        raise _identity_error(exc) from exc

    linked_patient_id = await _persist_verified_identity(
        db=db,
        current_db_user=current_db_user,
        session_id=payload.session_id,
        purpose=OtpPurpose.ENROL_BY_AADHAAR,
        issued=issued,
    )
    return AbhaIssuedOut(
        abha_number=issued.abha_number,
        abha_address=issued.abha_address,
        name=issued.name,
        gender=issued.gender,
        date_of_birth=issued.date_of_birth,
        linked_patient_id=linked_patient_id,
    )


@router.post(
    "/login/request-otp",
    response_model=OtpRequestedOut,
    dependencies=[Depends(require_roles("receptionist", "doctor"))],
)
async def login_request_otp(
    payload: AbhaLoginOtpRequest,
    current_db_user: CurrentDbUser,
    db: DbSession,
) -> OtpRequestedOut:
    """Send an OTP for an ABHA the patient says they hold — to its linked
    mobile (ABHA number) or through Aadhaar (Aadhaar number)."""
    await _get_patient_or_404(db, payload.patient_id, current_db_user.facility_id)
    try:
        result = await identity_service.request_login_otp(
            abha_number=_normalise_abha(payload.abha_number) if payload.abha_number else None,
            aadhaar=payload.aadhaar,
            facility_id=str(current_db_user.facility_id),
            started_by=str(current_db_user.id),
            patient_id=str(payload.patient_id),
        )
    except AbdmNotConfigured:
        raise _unavailable("ABDM credentials are not configured on this server") from None
    except AbdmPublicKeyMissing:
        raise _unavailable("ABDM public certificate is not configured on this server") from None
    except AbdmUnavailable:
        raise _unavailable("ABDM did not respond") from None
    except AbdmRejected as exc:
        log.warning("ABDM declined a login OTP request (%s)", exc.status_code)
        raise HTTPException(
            502,
            {
                "code": "abdm_rejected",
                "message": "ABDM declined the request",
            },
        ) from exc
    except identity_service.AbdmIdentityError as exc:
        raise _identity_error(exc) from exc

    return OtpRequestedOut(
        session_id=result.session_id,
        masked_mobile=result.masked_mobile,
        resends_remaining=result.resends_remaining,
    )


@router.post(
    "/login/resend-otp",
    response_model=OtpRequestedOut,
    dependencies=[Depends(require_roles("receptionist", "doctor"))],
)
async def login_resend_otp(
    payload: OtpResendRequest,
    current_db_user: CurrentDbUser,
    db: DbSession,
) -> OtpRequestedOut:
    """Fresh login OTP for the same patient and desk attempt (VRFY_ABHA_305/405)."""
    await _get_patient_or_404(db, payload.patient_id, current_db_user.facility_id)
    return await _resend(payload, current_db_user, db, OtpPurpose.LOGIN_BY_ABHA)


@router.post(
    "/login/verify-otp",
    response_model=AbhaIssuedOut,
    dependencies=[Depends(require_roles("receptionist", "doctor"))],
)
async def login_verify_otp(
    payload: OtpVerifyRequest,
    current_db_user: CurrentDbUser,
    db: DbSession,
) -> AbhaIssuedOut:
    """The OTP proves the patient holds this ABHA."""
    try:
        await _bound_otp_session(db, current_db_user, payload.session_id, OtpPurpose.LOGIN_BY_ABHA)
        issued = await identity_service.verify_login_otp(
            session_id=payload.session_id,
            otp=payload.otp,
            facility_id=str(current_db_user.facility_id),
            consume_session=False,
        )
    except (OtpSessionNotFound, OtpSessionMismatch):
        raise HTTPException(
            404,
            {
                "code": "otp_session_not_found",
                "message": "This OTP session has expired or does not exist",
            },
        ) from None
    except AbdmNotConfigured:
        raise _unavailable("ABDM credentials are not configured on this server") from None
    except AbdmPublicKeyMissing:
        raise _unavailable("ABDM public certificate is not configured on this server") from None
    except AbdmUnavailable:
        raise _unavailable("ABDM did not respond") from None
    except AbdmRejected as exc:
        raise _otp_rejected(exc, "login") from exc
    except identity_service.AbdmIdentityError as exc:
        raise _identity_error(exc) from exc

    linked_patient_id = await _persist_verified_identity(
        db=db,
        current_db_user=current_db_user,
        session_id=payload.session_id,
        purpose=OtpPurpose.LOGIN_BY_ABHA,
        issued=issued,
    )
    return AbhaIssuedOut(
        abha_number=issued.abha_number,
        abha_address=issued.abha_address,
        name=issued.name,
        gender=issued.gender,
        date_of_birth=issued.date_of_birth,
        linked_patient_id=linked_patient_id,
    )

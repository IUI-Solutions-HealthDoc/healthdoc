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
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AuthUser, CurrentDbUser, get_current_user, require_roles
from app.common.db import get_db
from app.common.security import encrypt_pii
from app.integrations.abdm.client import (
    AbdmAuthError,
    AbdmNotConfigured,
    AbdmRejected,
    AbdmUnavailable,
    get_abdm_client,
)
from app.integrations.abdm.identity import service as identity_service
from app.integrations.abdm.identity.crypto import AbdmPublicKeyMissing
from app.integrations.abdm.identity.otp_session import (
    OtpSessionMismatch,
    OtpSessionNotFound,
)
from app.outbox.service import enqueue
from app.patients.models import Patient

log = logging.getLogger("healthdoc.abdm")
router = APIRouter(prefix="/abdm/abha", tags=["abdm"])

#: The ABDM v3 path that verifies an ABHA number. DELIBERATELY None.
#:
#: The old value was wrong (`/v3/hip/token/on-generate` is a callback the
#: gateway invokes on the HIP, not something a HIP posts to). The honest
#: replacement is not a better-looking guess — a plausible constant is worse
#: than an absent one, because the next person will believe it.
#:
#: While this is None the call is inert and says so. Set it from the ABDM v3
#: specification as the first step of M1 and verification starts working; no
#: other line needs to change.
_VERIFY_PATH: str | None = None


class AbhaCapture(BaseModel):
    patient_id: str
    abha_number: str
    linking_token: str        # from ABDM; encrypted before storage, never persisted raw


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

    STILL OUTSTANDING — read before trusting this
    ---------------------------------------------
    AUTH IS FIXED. THE ENDPOINT IS NOT. `_VERIFY_PATH` is None, so this returns
    None without calling anything, and every ABHA is recorded unverified — the
    same OUTCOME as before, reached honestly instead of via a doomed request
    that leaked the client secret into an Authorization header.

    Set `_VERIFY_PATH` from the ABDM v3 spec to turn verification on. That is
    M1's first task and the only line that needs to change.
    """
    # Ordered most-certain-first: an unknown path and absent credentials are
    # both facts we hold locally, and neither should reach the network.
    if _VERIFY_PATH is None:
        log.info("ABDM verify path not yet set from the v3 spec — "
                 "ABHA recorded without gateway verification")
        return None

    client = get_abdm_client()

    # Unconfigured is not a failure, and must not put a placeholder secret on
    # the wire. Checked here rather than caught as AbdmNotConfigured so the
    # request is never built at all.
    if not client.is_configured:
        log.info("ABDM not configured — ABHA recorded without gateway verification")
        return None

    try:
        response = await client.request("POST", _VERIFY_PATH, json={"abhaNumber": abha_number})
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
        # The gateway answered and declined. Status only; the body can carry PHI.
        log.warning("ABDM declined ABHA verification (%s)", exc.status_code)
        return None

    body = response.body
    # A 2xx whose body is not an object is not a verification. Returning it
    # would make `gateway_result is not None` true on a bare `null` or `""`.
    if not isinstance(body, dict):
        log.warning("ABDM returned %s with a non-object body — treating as unverified",
                    response.status_code)
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


@router.post("/link", dependencies=[Depends(require_roles("receptionist", "doctor"))])
async def link_abha(payload: AbhaCapture,
                    user: Annotated[AuthUser, Depends(get_current_user)],
                    db: AsyncSession = Depends(get_db)) -> dict:
    user_row = (await db.execute(
        text("SELECT id, facility_id FROM users WHERE keycloak_sub = :sub"),
        {"sub": user.sub},
    )).mappings().one_or_none()
    if user_row is None:
        raise HTTPException(403, "Authenticated user has no HealthDoc profile")

    # An ABHA belongs to exactly one person. patients.abha_number is UNIQUE, so
    # without this the collision surfaces as an IntegrityError 500 rather than
    # something a receptionist can act on.
    normalised = _normalise_abha(payload.abha_number)
    clash = (await db.execute(
        select(Patient.id).where(
            Patient.abha_number == normalised,
            Patient.id != payload.patient_id,
        )
    )).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(409, {
            "code": "duplicate_abha",
            "message": "This ABHA number is already linked to another patient",
        })

    # Try verifying with ABDM — gracefully degrade if gateway is down
    gateway_result = await _verify_with_gateway(payload.abha_number)
    gateway_verified = gateway_result is not None

    blob, key_version = encrypt_pii(payload.linking_token)
    result = await db.execute(text("""
        UPDATE patients
        SET abha_number = :abha,
            abha_linking_token_encrypted = :blob,
            abha_linking_key_version = :kv,
            abha_linked_at = now(), updated_at = now(), updated_by = :uid,
            identity_status = CASE WHEN :verified THEN identity_status ELSE 'identity_unverified' END
        WHERE id = :pid AND facility_id = :facility_id
    """), {"abha": payload.abha_number, "blob": blob, "kv": key_version,
           "pid": payload.patient_id, "uid": user_row["id"],
           "facility_id": user_row["facility_id"], "verified": gateway_verified})
    if result.rowcount != 1:
        raise HTTPException(404, "Patient not found in caller facility")
    await enqueue(db, aggregate_type="patient", aggregate_id=payload.patient_id,
                  event_type="abha_linked", payload={"abha_number": payload.abha_number},
                  sensitivity="important")
    return {"patient_id": payload.patient_id, "abha_linked": True,
            "gateway_verified": gateway_verified}


@router.get(
    "/patients/{patient_id}/abha",
    response_model=AbhaOut,
    dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "admin"))],
)
async def get_abha(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
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
        raise HTTPException(409, {
            "code": "no_abha_linked",
            "message": "Patient has no ABHA number linked",
        })

    patient.abha_number = None
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


class AbhaLoginOtpRequest(BaseModel):
    abha_number: str
    #: Optional: attach the verified ABHA to a patient already registered here.
    patient_id: uuid.UUID | None = None


class OtpVerifyRequest(BaseModel):
    session_id: str
    otp: str = Field(min_length=4, max_length=8, pattern=r"^\d{4,8}$")
    #: Enrolment only — the mobile to attach to the new ABHA.
    mobile: str | None = Field(default=None, pattern=r"^\d{10}$")


class OtpRequestedOut(BaseModel):
    session_id: str
    masked_mobile: str | None = None


class AbhaIssuedOut(BaseModel):
    abha_number: str
    abha_address: str | None = None
    name: str | None = None
    gender: str | None = None
    date_of_birth: str | None = None
    #: Deliberately absent: the linking token. It is a credential, it is stored
    #: encrypted server-side by the link endpoint, and a browser has no use for
    #: it. Returning it would put it in a response body, a proxy log and a
    #: React devtools tree for no gain.


def _identity_error(exc: identity_service.AbdmIdentityError) -> HTTPException:
    return HTTPException(502, {"code": exc.code, "message": exc.message})


def _unavailable(reason: str) -> HTTPException:
    return HTTPException(503, {"code": "abdm_unavailable", "message": reason})


@router.post(
    "/enrol/aadhaar/request-otp",
    response_model=OtpRequestedOut,
    dependencies=[Depends(require_roles("receptionist", "doctor"))],
)
async def enrol_request_otp(
    payload: AadhaarOtpRequest,
    current_db_user: CurrentDbUser,
) -> OtpRequestedOut:
    """Send an OTP to the mobile registered against this Aadhaar.

    The Aadhaar number is encrypted in this call and referenced nowhere after
    it — not in the OTP session, not in an audit row, not in a log line.
    """
    try:
        result = await identity_service.request_aadhaar_otp(
            aadhaar=payload.aadhaar,
            facility_id=str(current_db_user.facility_id),
            started_by=str(current_db_user.id),
        )
    except AbdmNotConfigured:
        raise _unavailable("ABDM credentials are not configured on this server")
    except AbdmPublicKeyMissing:
        raise _unavailable("ABDM public certificate is not configured on this server")
    except AbdmUnavailable:
        raise _unavailable("ABDM did not respond")
    except AbdmRejected as exc:
        # Status only. The gateway's body can echo the identifier we just sent.
        log.warning("ABDM declined an enrolment OTP request (%s)", exc.status_code)
        raise HTTPException(502, {
            "code": "abdm_rejected",
            "message": "ABDM declined the request",
        })
    except identity_service.AbdmIdentityError as exc:
        raise _identity_error(exc)

    return OtpRequestedOut(session_id=result.session_id, masked_mobile=result.masked_mobile)


@router.post(
    "/enrol/aadhaar/verify-otp",
    response_model=AbhaIssuedOut,
    dependencies=[Depends(require_roles("receptionist", "doctor"))],
)
async def enrol_verify_otp(
    payload: OtpVerifyRequest,
    current_db_user: CurrentDbUser,
) -> AbhaIssuedOut:
    """Present the OTP and receive a newly created ABHA."""
    try:
        issued = await identity_service.enrol_by_aadhaar_otp(
            session_id=payload.session_id,
            otp=payload.otp,
            mobile=payload.mobile,
            facility_id=str(current_db_user.facility_id),
        )
    except (OtpSessionNotFound, OtpSessionMismatch):
        # One response for expired, already-spent, wrong-facility and
        # wrong-purpose. Distinguishing them would confirm that someone else's
        # transaction exists, which is the enumeration oracle this codebase
        # avoids with 404-not-403 everywhere else.
        raise HTTPException(404, {
            "code": "otp_session_not_found",
            "message": "This OTP session has expired or does not exist",
        })
    except AbdmNotConfigured:
        raise _unavailable("ABDM credentials are not configured on this server")
    except AbdmPublicKeyMissing:
        raise _unavailable("ABDM public certificate is not configured on this server")
    except AbdmUnavailable:
        raise _unavailable("ABDM did not respond")
    except AbdmRejected as exc:
        log.warning("ABDM declined an enrolment verification (%s)", exc.status_code)
        raise HTTPException(502, {
            "code": "abdm_rejected",
            "message": "ABDM declined the OTP",
        })
    except identity_service.AbdmIdentityError as exc:
        raise _identity_error(exc)

    return AbhaIssuedOut(
        abha_number=issued.abha_number,
        abha_address=issued.abha_address,
        name=issued.name,
        gender=issued.gender,
        date_of_birth=issued.date_of_birth,
    )


@router.post(
    "/login/request-otp",
    response_model=OtpRequestedOut,
    dependencies=[Depends(require_roles("receptionist", "doctor"))],
)
async def login_request_otp(
    payload: AbhaLoginOtpRequest,
    current_db_user: CurrentDbUser,
) -> OtpRequestedOut:
    """Send an OTP to the mobile behind an ABHA the patient says they hold."""
    try:
        result = await identity_service.request_login_otp(
            abha_number=_normalise_abha(payload.abha_number),
            facility_id=str(current_db_user.facility_id),
            started_by=str(current_db_user.id),
            patient_id=str(payload.patient_id) if payload.patient_id else None,
        )
    except AbdmNotConfigured:
        raise _unavailable("ABDM credentials are not configured on this server")
    except AbdmPublicKeyMissing:
        raise _unavailable("ABDM public certificate is not configured on this server")
    except AbdmUnavailable:
        raise _unavailable("ABDM did not respond")
    except AbdmRejected as exc:
        log.warning("ABDM declined a login OTP request (%s)", exc.status_code)
        raise HTTPException(502, {
            "code": "abdm_rejected",
            "message": "ABDM declined the request",
        })
    except identity_service.AbdmIdentityError as exc:
        raise _identity_error(exc)

    return OtpRequestedOut(session_id=result.session_id, masked_mobile=result.masked_mobile)


@router.post(
    "/login/verify-otp",
    response_model=AbhaIssuedOut,
    dependencies=[Depends(require_roles("receptionist", "doctor"))],
)
async def login_verify_otp(
    payload: OtpVerifyRequest,
    current_db_user: CurrentDbUser,
) -> AbhaIssuedOut:
    """The OTP proves the patient holds this ABHA."""
    try:
        issued = await identity_service.verify_login_otp(
            session_id=payload.session_id,
            otp=payload.otp,
            facility_id=str(current_db_user.facility_id),
        )
    except (OtpSessionNotFound, OtpSessionMismatch):
        raise HTTPException(404, {
            "code": "otp_session_not_found",
            "message": "This OTP session has expired or does not exist",
        })
    except AbdmNotConfigured:
        raise _unavailable("ABDM credentials are not configured on this server")
    except AbdmPublicKeyMissing:
        raise _unavailable("ABDM public certificate is not configured on this server")
    except AbdmUnavailable:
        raise _unavailable("ABDM did not respond")
    except AbdmRejected as exc:
        log.warning("ABDM declined a login verification (%s)", exc.status_code)
        raise HTTPException(502, {
            "code": "abdm_rejected",
            "message": "ABDM declined the OTP",
        })
    except identity_service.AbdmIdentityError as exc:
        raise _identity_error(exc)

    return AbhaIssuedOut(
        abha_number=issued.abha_number,
        abha_address=issued.abha_address,
        name=issued.name,
        gender=issued.gender,
        date_of_birth=issued.date_of_birth,
    )

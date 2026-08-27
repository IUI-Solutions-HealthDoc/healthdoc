"""ABDM M1 — creating, verifying and authenticating an ABHA.

WHAT M1 IS

Digital patient identity: at registration, a patient either creates an ABHA
(Ayushman Bharat Health Account) from their Aadhaar, or proves they already
hold one. Both are two-legged OTP exchanges — request, then verify — and both
go through `otp_session` so our half of the exchange lives in Redis with a TTL
rather than in Postgres forever.

THE THREE FLOWS

    enrol_by_aadhaar    Aadhaar + OTP -> a NEW ABHA number
    login_by_abha       existing ABHA + OTP -> proof the patient holds it
    (verify_mobile)     reserved; the OtpPurpose exists, the flow does not yet

WHAT NEVER TOUCHES THE DATABASE

The Aadhaar number. It is encrypted, sent, and dropped. `otp_session` holds no
copy, this module holds no copy, and nothing here writes one. The durable
record is `patients.abha_number` plus the encrypted linking token — the
identity, not the credential that established it.

The OTP is never seen by us at all in the sense that matters: it arrives in a
request, is encrypted, and is forwarded. It is not logged, not stored, and not
returned.

PATHS ARE CONFIGURATION, NOT CONSTANTS

Every gateway path here comes from settings. That is deliberate and the reason
is specific: the previous ABHA call in this repo hardcoded
`/v3/hip/token/on-generate` — a callback ABDM invokes ON a HIP, not an endpoint
a HIP posts to — and because its errors were swallowed, it 401'd silently for
the entire life of the file. **The defaults below are the documented v3 shapes
and have NOT been confirmed against the sandbox.** When one is wrong, the fix
is an environment variable, not a release.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.integrations.abdm.client import AbdmResponse, get_abdm_client
from app.common.config import get_settings

from . import otp_session
from .crypto import encrypt_for_abdm
from .otp_session import OtpPurpose, OtpSession

log = logging.getLogger("healthdoc.abdm")


class AbdmIdentityError(Exception):
    """A flow could not complete. Carries an operator-facing reason only."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class OtpRequested:
    """First leg done. `session_id` is OURS — ABDM's txn id never leaves the server."""

    session_id: str
    #: Masked, as ABDM returns it: enough for the patient to recognise which
    #: phone to check, not enough to be a new disclosure of their number.
    masked_mobile: str | None


@dataclass(frozen=True)
class AbhaIssued:
    abha_number: str
    #: The ABHA address (PHR), e.g. "name@abdm". Distinct from the number.
    abha_address: str | None
    #: Short-lived token proving this enrolment. Stored ENCRYPTED by the caller;
    #: never logged and never returned to a browser.
    linking_token: str | None
    name: str | None
    gender: str | None
    date_of_birth: str | None


def _txn_id(body: object) -> str:
    """Pull ABDM's transaction id out of a response body.

    ABDM has used `txnId` and `transactionId` across versions and endpoints.
    Accepting both is not sloppiness — it is cheaper than a flow that dies on a
    field rename, and the alternative is picking one and being wrong half the
    time. If neither is present the response is not what we think it is, and
    guessing further would build state on a misread.
    """
    if not isinstance(body, dict):
        raise AbdmIdentityError("abdm_bad_response", "gateway returned a non-object body")
    for key in ("txnId", "transactionId", "txnID"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    raise AbdmIdentityError(
        "abdm_bad_response", "gateway response carried no transaction id"
    )


async def _post(path: str, payload: dict) -> AbdmResponse:
    """POST to the ABHA host, which is NOT the HIECM gateway host.

    Enrolment and login live on abdm_abha_base_url; sessions live on
    abdm_gateway_base_url. Sending an enrolment to the gateway origin produces
    a 404 that reads like a broken account rather than a wrong host.
    """
    settings = get_settings()
    client = get_abdm_client()
    return await client.request(
        "POST", f"{settings.abdm_abha_base_url.rstrip('/')}{path}", json=payload
    )


# ------------------------------------------------------- enrol by Aadhaar

async def request_aadhaar_otp(
    *, aadhaar: str, facility_id: str, started_by: str
) -> OtpRequested:
    """Leg one of enrolment: ask ABDM to OTP the mobile linked to this Aadhaar.

    `aadhaar` is encrypted here and referenced nowhere afterwards — not in the
    session, not in a log, not in an audit row. The transaction id ABDM returns
    is what stands for this identity from now on.
    """
    settings = get_settings()
    body = (
        await _post(
            settings.abdm_path_enrol_request_otp,
            {
                "txnId": "",
                "scope": ["abha-enrol"],
                "loginHint": "aadhaar",
                "otpSystem": "aadhaar",
                "loginId": encrypt_for_abdm(aadhaar),
            },
        )
    ).body

    session = await otp_session.start(
        abdm_txn_id=_txn_id(body),
        purpose=OtpPurpose.ENROL_BY_AADHAAR,
        facility_id=facility_id,
        started_by=started_by,
    )
    return OtpRequested(
        session_id=session.session_id,
        masked_mobile=(body.get("message") if isinstance(body, dict) else None),
    )


async def enrol_by_aadhaar_otp(
    *, session_id: str, otp: str, mobile: str | None, facility_id: str
) -> AbhaIssued:
    """Leg two: present the OTP and receive a new ABHA.

    The session is consumed only on success. A mistyped digit leaves it alive so
    the patient can try again inside the same ABDM transaction — ABDM counts
    those attempts and will end the transaction itself.
    """
    session: OtpSession = await otp_session.load(
        session_id, facility_id=facility_id, purpose=OtpPurpose.ENROL_BY_AADHAAR
    )

    payload: dict = {
        "authData": {
            "authMethods": ["otp"],
            "otp": {
                "timeStamp": None,
                "txnId": session.abdm_txn_id,
                "otpValue": encrypt_for_abdm(otp),
            },
        },
        "consent": {"code": "abha-enrollment", "version": "1.4"},
    }
    if mobile:
        payload["authData"]["otp"]["mobile"] = encrypt_for_abdm(mobile)

    body = (await _post(get_settings().abdm_path_enrol_by_aadhaar, payload)).body
    if not isinstance(body, dict):
        raise AbdmIdentityError("abdm_bad_response", "gateway returned a non-object body")

    profile = body.get("ABHAProfile") or body.get("abhaProfile") or {}
    abha_number = profile.get("ABHANumber") or profile.get("abhaNumber")
    if not abha_number:
        # Do not invent success. An enrolment with no number is a failure that
        # would otherwise be written to a patient record as a verified identity.
        raise AbdmIdentityError(
            "abdm_no_abha_returned", "enrolment completed without an ABHA number"
        )

    await otp_session.finish(session_id)
    return AbhaIssued(
        abha_number=abha_number,
        abha_address=profile.get("phrAddress") or profile.get("abhaAddress"),
        linking_token=body.get("token") or body.get("tokens", {}).get("token"),
        name=profile.get("name"),
        gender=profile.get("gender"),
        date_of_birth=profile.get("dob") or profile.get("dateOfBirth"),
    )


# ---------------------------------------------------------- login by ABHA

async def request_login_otp(
    *, abha_number: str, facility_id: str, started_by: str, patient_id: str | None = None
) -> OtpRequested:
    """Leg one of proving an EXISTING ABHA belongs to the person at the desk."""
    settings = get_settings()
    body = (
        await _post(
            settings.abdm_path_login_request_otp,
            {
                "scope": ["abha-login", "mobile-verify"],
                "loginHint": "abha-number",
                "otpSystem": "abdm",
                "loginId": encrypt_for_abdm(abha_number),
            },
        )
    ).body

    session = await otp_session.start(
        abdm_txn_id=_txn_id(body),
        purpose=OtpPurpose.LOGIN_BY_ABHA,
        facility_id=facility_id,
        started_by=started_by,
        patient_id=patient_id,
    )
    return OtpRequested(
        session_id=session.session_id,
        masked_mobile=(body.get("message") if isinstance(body, dict) else None),
    )


async def verify_login_otp(
    *, session_id: str, otp: str, facility_id: str
) -> AbhaIssued:
    """Leg two: the OTP proves the patient holds this ABHA."""
    session = await otp_session.load(
        session_id, facility_id=facility_id, purpose=OtpPurpose.LOGIN_BY_ABHA
    )

    body = (
        await _post(
            get_settings().abdm_path_login_verify,
            {
                "scope": ["abha-login", "mobile-verify"],
                "authData": {
                    "authMethods": ["otp"],
                    "otp": {
                        "txnId": session.abdm_txn_id,
                        "otpValue": encrypt_for_abdm(otp),
                    },
                },
            },
        )
    ).body
    if not isinstance(body, dict):
        raise AbdmIdentityError("abdm_bad_response", "gateway returned a non-object body")

    profile = body.get("ABHAProfile") or body.get("abhaProfile") or {}
    abha_number = profile.get("ABHANumber") or profile.get("abhaNumber")
    if not abha_number:
        raise AbdmIdentityError(
            "abdm_no_abha_returned", "login completed without an ABHA number"
        )

    await otp_session.finish(session_id)
    return AbhaIssued(
        abha_number=abha_number,
        abha_address=profile.get("phrAddress") or profile.get("abhaAddress"),
        linking_token=body.get("token"),
        name=profile.get("name"),
        gender=profile.get("gender"),
        date_of_birth=profile.get("dob") or profile.get("dateOfBirth"),
    )

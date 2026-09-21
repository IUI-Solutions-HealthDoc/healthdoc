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
    enrol continuation  same txn: communication-mobile OTP, suggested address
    (verify_mobile)     OtpPurpose still exists; continuation stays on the
                        enrolment session so the ABDM txn id is not split

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
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from app.common.config import get_settings
from app.integrations.abdm.client import AbdmRejected, AbdmResponse, get_abdm_client

from . import otp_session
from .crypto import encrypt_for_abdm
from .enrolment_consent import (
    APPROVED_CONSENT_LANGUAGES,
    ENROLMENT_CONSENT_CODE,
    ENROLMENT_CONSENT_VERSION,
    EnrolmentConsent,
)
from .formatting import hyphenate_abha
from .otp_session import OtpPurpose, OtpSession

STAGE_ENROL_OTP = "enrol_otp"
STAGE_MOBILE_PENDING = "mobile_pending"
STAGE_MOBILE_OTP = "mobile_otp"
STAGE_ADDRESS_PENDING = "address_pending"

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
    #: Fresh OTP requests still available for this desk attempt.
    resends_remaining: int = otp_session.MAX_RESENDS


#: Login scopes per identifier, from the official M1 v3 collection
#: ("ABHA Verification" → "Verify Via ABHA Number" / "Verify via Aadhaar").
#: The verify leg must quote the same scope as the request leg.
_LOGIN_SCOPES: dict[str, list[str]] = {
    "abha-number": ["abha-login", "mobile-verify"],
    "aadhaar": ["abha-login", "aadhaar-verify"],
    # Official collection: address and communication-mobile both OTP through ABDM.
    "abha-address": ["abha-login", "mobile-verify"],
    "mobile": ["abha-login", "mobile-verify"],
}
_LOGIN_OTP_SYSTEMS: dict[str, str] = {
    "abha-number": "abdm",
    "aadhaar": "aadhaar",
    "abha-address": "abdm",
    "mobile": "abdm",
}


@dataclass(frozen=True)
class AbhaIssued:
    abha_number: str
    #: The ABHA address (PHR), e.g. "name@abdm". Distinct from the number.
    abha_address: str | None
    #: Profile/X-token from enrolment or login. This is NOT a HIP linking token.
    #: Stored ENCRYPTED by the caller as a profile credential; never logged and
    #: never returned to a browser; never written to abha_linking_token_*.
    linking_token: str | None
    name: str | None
    gender: str | None
    date_of_birth: str | None
    next_step: str = "complete"
    suggested_addresses: tuple[str, ...] = ()
    #: (ABHA number, display name) when the desk must choose. Never a guess.
    account_choices: tuple[tuple[str, str | None], ...] = ()


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
    raise AbdmIdentityError("abdm_bad_response", "gateway response carried no transaction id")


async def _call(
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    extra_headers: dict[str, str] | None = None,
    parse_json: bool = True,
) -> AbdmResponse:
    """Call the ABHA host, which is NOT the HIECM gateway host.

    Enrolment and login live on abdm_abha_base_url; sessions live on
    abdm_gateway_base_url. Sending an enrolment to the gateway origin produces
    a 404 that reads like a broken account rather than a wrong host.
    """
    settings = get_settings()
    client = get_abdm_client()
    try:
        return await client.request(
            method,
            f"{settings.abdm_abha_base_url.rstrip('/')}{path}",
            json=payload,
            extra_headers=extra_headers,
            parse_json=parse_json,
        )
    except AbdmRejected as exc:
        # Error bodies can echo the identifier or OTP. Retain only contracted
        # field names and error-code syntax, never values or free-form messages.
        codes, fields = _rejection_metadata(exc.detail)
        log.warning(
            "ABDM identity rejected (status=%s request=%s codes=%s fields=%s)",
            exc.status_code, exc.request_id, codes, fields,
        )
        raise


async def _post(path: str, payload: dict) -> AbdmResponse:
    return await _call("POST", path, payload)


def _rejection_metadata(detail: object) -> tuple[list[str], list[str]]:
    codes: set[str] = set()
    fields: set[str] = set()
    allowed_fields = {
        "loginId", "loginHint", "scope", "otpSystem", "otpValue", "txnId",
        "abhaAddress", "preferred",
    }

    def visit(value: object, depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if key in allowed_fields:
                    fields.add(key)
                if key == "code" and isinstance(child, str) and re.fullmatch(r"ABDM-\d{4}", child):
                    codes.add(child)
                if key in {"field", "property"} and isinstance(child, str) and child in allowed_fields:
                    fields.add(child)
                if isinstance(child, dict | list):
                    visit(child, depth + 1)
        elif isinstance(value, list):
            for child in value[:50]:
                visit(child, depth + 1)

    visit(detail)
    return sorted(codes), sorted(fields)


def _address(profile: dict) -> str | None:
    """Enrolment returns phrAddress[], login returns preferredAbhaAddress.

    A database scalar cannot hold the former. If there are multiple addresses
    with no declared preference, leave it unset; choosing one is not our call.
    """
    preferred = profile.get("preferredAbhaAddress") or profile.get("abhaAddress")
    if isinstance(preferred, str) and preferred.strip():
        return preferred.strip()
    addresses = profile.get("phrAddress")
    if isinstance(addresses, str):
        return addresses.strip() or None
    if isinstance(addresses, list) and len(addresses) == 1 and isinstance(addresses[0], str):
        return addresses[0].strip() or None
    return None


def _name(profile: dict) -> str | None:
    if isinstance(profile.get("name"), str) and profile["name"].strip():
        return profile["name"].strip()
    return " ".join(
        part.strip() for key in ("firstName", "middleName", "lastName")
        if isinstance(part := profile.get(key), str) and part.strip()
    ) or None


def _require_enrolment_consent(consent: EnrolmentConsent | None) -> EnrolmentConsent:
    if consent is None:
        raise AbdmIdentityError(
            "enrolment_consent_required",
            "Enrolment requires an explicit patient consent grant",
        )
    if not consent.granted:
        raise AbdmIdentityError(
            "enrolment_consent_refused",
            "Enrolment cannot continue without the patient's consent",
        )
    if consent.code != ENROLMENT_CONSENT_CODE or consent.version != ENROLMENT_CONSENT_VERSION:
        raise AbdmIdentityError(
            "enrolment_consent_mismatch",
            "Enrolment consent code or version does not match the approved grant",
        )
    language = consent.language.strip().lower()
    if language not in APPROVED_CONSENT_LANGUAGES:
        raise AbdmIdentityError(
            "enrolment_consent_language_unavailable",
            "No approved translation of this consent is available in that language",
        )
    return EnrolmentConsent(
        granted=True,
        code=ENROLMENT_CONSENT_CODE,
        version=ENROLMENT_CONSENT_VERSION,
        language=language,
    )


def _consent_from_session(session: OtpSession) -> dict[str, str]:
    """Wire consent comes from the captured grant, never a hardcoded fallback."""
    if (
        session.consent_code != ENROLMENT_CONSENT_CODE
        or session.consent_version != ENROLMENT_CONSENT_VERSION
        or not session.consent_granted_at
    ):
        raise AbdmIdentityError(
            "enrolment_consent_required",
            "Enrolment requires an explicit patient consent grant",
        )
    return {"code": session.consent_code, "version": session.consent_version}


def _profile_token(body: dict) -> str | None:
    """Enrolment/login X-token. Never treat a refresh token as the profile credential."""
    nested = body.get("tokens")
    if isinstance(nested, dict):
        token = nested.get("token")
        if isinstance(token, str) and token:
            return token
    token = body.get("token")
    return token if isinstance(token, str) and token else None


def _abdm_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _require_stage(session: OtpSession, *allowed: str) -> None:
    if session.stage not in allowed:
        raise AbdmIdentityError(
            "enrolment_stage_invalid",
            "This enrolment step is not available for the current session",
        )


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


# ------------------------------------------------------- enrol by Aadhaar


async def request_aadhaar_otp(
    *,
    aadhaar: str,
    facility_id: str,
    started_by: str,
    patient_id: str | None = None,
    resends: int = 0,
    consent: EnrolmentConsent | None = None,
    consent_granted_at: str | None = None,
) -> OtpRequested:
    """Leg one of enrolment: ask ABDM to OTP the mobile linked to this Aadhaar.

    `aadhaar` is encrypted here and referenced nowhere afterwards — not in the
    session, not in a log, not in an audit row. The transaction id ABDM returns
    is what stands for this identity from now on. Consent must already have been
    granted at the desk; this call does not invent it.
    """
    granted = _require_enrolment_consent(consent)
    settings = get_settings()
    body = (
        await _post(
            settings.abdm_path_enrol_request_otp,
            {
                # Always a fresh transaction, including on resend: the official
                # collection has no separate resend call, and quoting an old
                # txnId here is the mobile-verify continuation, not a resend.
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
        patient_id=patient_id,
        login_hint="aadhaar",
        resends=resends,
        consent_code=granted.code,
        consent_version=granted.version,
        consent_language=granted.language,
        consent_granted_at=consent_granted_at or datetime.now(UTC).isoformat(),
        stage=STAGE_ENROL_OTP,
    )
    return OtpRequested(
        session_id=session.session_id,
        masked_mobile=(body.get("message") if isinstance(body, dict) else None),
        resends_remaining=otp_session.MAX_RESENDS - resends,
    )


async def enrol_by_aadhaar_otp(
    *,
    session_id: str,
    otp: str,
    mobile: str | None,
    facility_id: str,
    consume_session: bool = True,
) -> AbhaIssued:
    """Leg two: present the OTP and receive a new ABHA.

    The session is consumed only on success. A mistyped digit leaves it alive so
    the patient can try again inside the same ABDM transaction — ABDM counts
    those attempts and will end the transaction itself.
    """
    session: OtpSession = await otp_session.load(
        session_id, facility_id=facility_id, purpose=OtpPurpose.ENROL_BY_AADHAAR
    )
    _require_stage(session, STAGE_ENROL_OTP, None)

    payload: dict = {
        "authData": {
            "authMethods": ["otp"],
            "otp": {
                "txnId": session.abdm_txn_id,
                "otpValue": encrypt_for_abdm(otp),
            },
        },
        "consent": _consent_from_session(session),
    }
    if mobile:
        # Unlike loginId/otpValue, byAadhaar's mobile is ten national digits
        # in the supplied M1 contract. TLS still protects the request; never log
        # this payload. The public API validates the mobile format first.
        payload["authData"]["otp"]["mobile"] = mobile

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

    if consume_session:
        await otp_session.finish(session_id)
    else:
        next_txn = body.get("txnId")
        await otp_session.save(otp_session.with_updates(
            session,
            abdm_txn_id=next_txn if isinstance(next_txn, str) and next_txn else session.abdm_txn_id,
            stage=STAGE_MOBILE_PENDING,
        ))
    return AbhaIssued(
        abha_number=abha_number,
        abha_address=_address(profile),
        linking_token=_profile_token(body),
        name=_name(profile),
        gender=profile.get("gender"),
        date_of_birth=profile.get("dob") or profile.get("dateOfBirth"),
        next_step="complete" if consume_session else "mobile_verify",
    )


# ---------------------------------------------------------- login by ABHA


def _login_id_for(hint: str, value: str) -> str:
    if hint == "abha-number":
        return hyphenate_abha(value)
    if hint == "aadhaar":
        return value
    if hint == "mobile":
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) != 10:
            raise AbdmIdentityError("abdm_identifier_required", "communication mobile must be 10 digits")
        return digits
    address = value.strip()
    if "@" not in address or " " in address:
        raise AbdmIdentityError("abha_address_invalid", "Enter the ABHA address to verify")
    return address


async def request_login_otp(
    *,
    abha_number: str | None = None,
    aadhaar: str | None = None,
    abha_address: str | None = None,
    mobile: str | None = None,
    facility_id: str,
    started_by: str,
    patient_id: str | None = None,
    resends: int = 0,
) -> OtpRequested:
    """Leg one of proving an EXISTING ABHA belongs to the person at the desk.

    Exactly one identifier. ABHA number and Aadhaar are the existing paths.
    ABHA address and communication mobile can return several accounts; the
    desk chooses one later. The identifier is not stored.
    """
    supplied = {
        "abha-number": abha_number,
        "aadhaar": aadhaar,
        "abha-address": abha_address,
        "mobile": mobile,
    }
    present = [hint for hint, value in supplied.items() if value is not None]
    if len(present) != 1:
        raise AbdmIdentityError(
            "abdm_identifier_required",
            "exactly one of ABHA number, Aadhaar, ABHA address or mobile is required",
        )
    login_hint = present[0]
    login_id = _login_id_for(login_hint, supplied[login_hint] or "")
    settings = get_settings()
    body = (
        await _post(
            settings.abdm_path_login_request_otp,
            {
                "scope": _LOGIN_SCOPES[login_hint],
                "loginHint": login_hint,
                "otpSystem": _LOGIN_OTP_SYSTEMS[login_hint],
                "loginId": encrypt_for_abdm(login_id),
            },
        )
    ).body

    session = await otp_session.start(
        abdm_txn_id=_txn_id(body),
        purpose=OtpPurpose.LOGIN_BY_ABHA,
        facility_id=facility_id,
        started_by=started_by,
        patient_id=patient_id,
        login_hint=login_hint,
        resends=resends,
    )
    return OtpRequested(
        session_id=session.session_id,
        masked_mobile=(body.get("message") if isinstance(body, dict) else None),
        resends_remaining=otp_session.MAX_RESENDS - resends,
    )


async def resend_otp(
    *,
    session_id: str,
    purpose: OtpPurpose,
    facility_id: str,
    started_by: str,
    abha_number: str | None = None,
    aadhaar: str | None = None,
    abha_address: str | None = None,
    mobile: str | None = None,
) -> OtpRequested:
    """Ask ABDM for a fresh OTP for the same desk attempt (workbook CRT_ABHA_106,
    VRFY_ABHA_305/405).

    The identifier is re-supplied by the desk because the session deliberately
    never stored it. The old session is consumed only after the gateway accepted
    the new request, so a failed resend leaves the previous OTP usable.
    """
    session = await otp_session.load(session_id, facility_id=facility_id, purpose=purpose)
    if session.started_by != str(started_by):
        raise otp_session.OtpSessionMismatch
    session.resend_allowed()
    if session.login_hint == "aadhaar" and aadhaar is None:
        raise AbdmIdentityError("abdm_identifier_required", "this exchange was started with an Aadhaar number")
    if session.login_hint == "abha-number" and abha_number is None:
        raise AbdmIdentityError("abdm_identifier_required", "this exchange was started with an ABHA number")
    if session.login_hint == "abha-address" and abha_address is None:
        raise AbdmIdentityError("abdm_identifier_required", "this exchange was started with an ABHA address")
    if session.login_hint == "mobile" and mobile is None:
        raise AbdmIdentityError("abdm_identifier_required", "this exchange was started with a communication mobile")
    common = {
        "facility_id": facility_id,
        "started_by": started_by,
        "patient_id": session.patient_id,
        "resends": session.resends + 1,
    }
    if purpose is OtpPurpose.ENROL_BY_AADHAAR:
        if aadhaar is None:
            raise AbdmIdentityError("abdm_identifier_required", "enrolment resend requires the Aadhaar number")
        if not session.consent_code:
            raise AbdmIdentityError(
                "enrolment_consent_required",
                "Enrolment requires an explicit patient consent grant",
            )
        requested = await request_aadhaar_otp(
            aadhaar=aadhaar,
            consent=EnrolmentConsent(
                granted=True,
                code=session.consent_code,
                version=session.consent_version or "",
                language=session.consent_language or "en",
            ),
            consent_granted_at=session.consent_granted_at,
            **common,
        )
    elif purpose is OtpPurpose.LOGIN_BY_ABHA:
        requested = await request_login_otp(
            abha_number=abha_number,
            aadhaar=aadhaar,
            abha_address=abha_address,
            mobile=mobile,
            **common,
        )
    else:
        raise AbdmIdentityError("abdm_resend_unsupported", "this exchange cannot be resent")
    await otp_session.finish(session_id)
    return requested


async def verify_login_otp(
    *, session_id: str, otp: str, facility_id: str, consume_session: bool = True
) -> AbhaIssued:
    """Leg two: the OTP proves the patient holds this ABHA."""
    session = await otp_session.load(
        session_id, facility_id=facility_id, purpose=OtpPurpose.LOGIN_BY_ABHA
    )

    body = (
        await _post(
            get_settings().abdm_path_login_verify,
            {
                # Same scope as the request leg; a session from before
                # login_hint existed was necessarily an ABHA-number login.
                "scope": _LOGIN_SCOPES.get(session.login_hint or "abha-number", _LOGIN_SCOPES["abha-number"]),
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

    # M1 profile/login/verify has a different response from enrollment.
    # An HTTP 200 can carry authResult=failed. Never fall back to an enrolment
    # profile or guess between accounts when the login result is ambiguous.
    if body.get("authResult") != "success":
        raise AbdmIdentityError("abdm_auth_failed", "ABDM did not verify this OTP")
    accounts = body.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        raise AbdmIdentityError("abdm_account_selection_required", "ABDM did not return a verified account")
    choices: list[tuple[str, str | None]] = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        number = account.get("ABHANumber") or account.get("abhaNumber")
        if not isinstance(number, str) or not number.strip():
            continue
        choices.append((number.replace("-", "").strip(), _name(account)))
    if len(choices) > 1:
        token = _profile_token(body)
        if not token:
            raise AbdmIdentityError(
                "abdm_bad_response",
                "ABDM returned several accounts without a selection credential",
            )
        next_txn = body.get("txnId")
        await otp_session.save(otp_session.with_updates(
            session,
            abdm_txn_id=next_txn if isinstance(next_txn, str) and next_txn else session.abdm_txn_id,
            stage="account_select",
            selection_token=token,
            account_choices=[number for number, _display in choices],
        ))
        return AbhaIssued(
            abha_number="",
            abha_address=None,
            linking_token=None,
            name=None,
            gender=None,
            date_of_birth=None,
            next_step="account_select",
            account_choices=tuple(choices),
        )
    if len(choices) != 1:
        raise AbdmIdentityError("abdm_account_selection_required", "ABDM did not return one verified account")
    profile = next(
        account for account in accounts
        if isinstance(account, dict)
        and str(account.get("ABHANumber") or account.get("abhaNumber") or "").replace("-", "").strip() == choices[0][0]
    )
    if profile.get("status") not in (None, "ACTIVE"):
        raise AbdmIdentityError("abdm_account_inactive", "This ABHA account is not active")
    abha_number = profile.get("ABHANumber") or profile.get("abhaNumber")
    if consume_session:
        await otp_session.finish(session_id)
    return AbhaIssued(
        abha_number=abha_number,
        abha_address=_address(profile),
        linking_token=_profile_token(body),
        name=_name(profile),
        gender=profile.get("gender"),
        date_of_birth=profile.get("dob") or profile.get("dateOfBirth"),
    )


async def select_login_account(
    *, session_id: str, abha_number: str, facility_id: str
) -> AbhaIssued:
    """Bind the account the desk chose. A number outside the OTP result is refused."""
    session = await otp_session.load(
        session_id, facility_id=facility_id, purpose=OtpPurpose.LOGIN_BY_ABHA
    )
    if session.stage != "account_select" or not session.selection_token:
        raise AbdmIdentityError(
            "enrolment_stage_invalid",
            "Choose an account only after ABDM returns more than one",
        )
    chosen = abha_number.replace("-", "").strip()
    if chosen not in (session.account_choices or []):
        raise AbdmIdentityError(
            "abha_account_not_in_selection",
            "That ABHA number was not one of the accounts ABDM returned",
        )
    settings = get_settings()
    body = (
        await _call(
            "POST",
            settings.abdm_path_login_verify_user,
            {"ABHANumber": hyphenate_abha(chosen), "txnId": session.abdm_txn_id},
            extra_headers={"T-token": _bearer(session.selection_token)},
        )
    ).body
    if not isinstance(body, dict):
        raise AbdmIdentityError("abdm_bad_response", "gateway returned a non-object body")
    if body.get("authResult") not in (None, "success"):
        raise AbdmIdentityError("abdm_auth_failed", "ABDM did not accept this account")
    returned = body.get("ABHANumber") or body.get("abhaNumber")
    if isinstance(returned, str) and returned.replace("-", "").strip() not in ("", chosen):
        raise AbdmIdentityError("abdm_bad_response", "ABDM confirmed a different ABHA number")
    profile = body.get("ABHAProfile") if isinstance(body.get("ABHAProfile"), dict) else body
    return AbhaIssued(
        abha_number=hyphenate_abha(chosen),
        abha_address=_address(profile) if isinstance(profile, dict) else None,
        linking_token=_profile_token(body) or session.selection_token,
        name=_name(profile) if isinstance(profile, dict) else None,
        gender=profile.get("gender") if isinstance(profile, dict) else None,
        date_of_birth=(profile.get("dob") or profile.get("dateOfBirth")) if isinstance(profile, dict) else None,
    )


@dataclass(frozen=True)
class AbhaCard:
    content: bytes
    media_type: str


@dataclass(frozen=True)
class AbhaProfileView:
    abha_number: str | None
    abha_address: str | None
    name: str | None
    gender: str | None
    status: str | None
    kyc_verified: bool | None


# -------------------------------- enrolment continuation (same ABDM txn)


def _bearer(token: str) -> str:
    value = token.strip()
    return value if value.lower().startswith("bearer ") else f"Bearer {value}"


async def request_enrolment_mobile_otp(
    *,
    session_id: str,
    mobile: str,
    facility_id: str,
    started_by: str,
    resend: bool = False,
) -> OtpRequested:
    """CRT_ABHA_108/109: communication-mobile OTP inside the enrolment txn.

    The mobile number is encrypted for the gateway and is not stored. A failed
    gateway call leaves the previous stage in place.
    """
    session = await otp_session.load(
        session_id, facility_id=facility_id, purpose=OtpPurpose.ENROL_BY_AADHAAR
    )
    if session.started_by != str(started_by):
        raise otp_session.OtpSessionMismatch
    if resend:
        _require_stage(session, STAGE_MOBILE_OTP)
        session.resend_allowed()
        resends = session.resends + 1
    else:
        _require_stage(session, STAGE_MOBILE_PENDING, STAGE_MOBILE_OTP)
        resends = 0 if session.stage == STAGE_MOBILE_PENDING else session.resends
    settings = get_settings()
    body = (
        await _post(
            settings.abdm_path_enrol_request_otp,
            {
                "txnId": session.abdm_txn_id,
                "scope": ["abha-enrol", "mobile-verify"],
                "loginHint": "mobile",
                "otpSystem": "abdm",
                "loginId": encrypt_for_abdm(mobile),
            },
        )
    ).body
    next_txn = session.abdm_txn_id
    if isinstance(body, dict):
        for key in ("txnId", "transactionId", "txnID"):
            value = body.get(key)
            if isinstance(value, str) and value:
                next_txn = value
                break
    await otp_session.save(otp_session.with_updates(
        session,
        abdm_txn_id=next_txn,
        stage=STAGE_MOBILE_OTP,
        resends=resends,
        created_at=datetime.now(UTC).isoformat(),
    ))
    return OtpRequested(
        session_id=session.session_id,
        masked_mobile=(body.get("message") if isinstance(body, dict) else None),
        resends_remaining=otp_session.MAX_RESENDS - resends,
    )


async def verify_enrolment_mobile_otp(
    *, session_id: str, otp: str, facility_id: str
) -> None:
    """Verify the communication-mobile OTP, then leave the session for address selection."""
    session = await otp_session.load(
        session_id, facility_id=facility_id, purpose=OtpPurpose.ENROL_BY_AADHAAR
    )
    _require_stage(session, STAGE_MOBILE_OTP)
    settings = get_settings()
    body = (
        await _post(
            settings.abdm_path_enrol_auth_by_abdm,
            {
                "scope": ["abha-enrol", "mobile-verify"],
                "authData": {
                    "authMethods": ["otp"],
                    "otp": {
                        "timeStamp": _abdm_timestamp(),
                        "txnId": session.abdm_txn_id,
                        "otpValue": encrypt_for_abdm(otp),
                    },
                },
            },
        )
    ).body
    if not isinstance(body, dict):
        raise AbdmIdentityError("abdm_bad_response", "gateway returned a non-object body")
    if body.get("authResult") not in (None, "success"):
        raise AbdmIdentityError("abdm_auth_failed", "ABDM did not verify this OTP")
    accounts = body.get("accounts")
    if isinstance(accounts, list) and len(accounts) > 1:
        raise AbdmIdentityError(
            "abdm_account_selection_required",
            "ABDM returned more than one account; the desk must not pick the first",
        )
    next_txn = body.get("txnId")
    await otp_session.save(otp_session.with_updates(
        session,
        abdm_txn_id=next_txn if isinstance(next_txn, str) and next_txn else session.abdm_txn_id,
        stage=STAGE_ADDRESS_PENDING,
    ))


async def list_enrolment_address_suggestions(
    *, session_id: str, facility_id: str
) -> tuple[str, ...]:
    session = await otp_session.load(
        session_id, facility_id=facility_id, purpose=OtpPurpose.ENROL_BY_AADHAAR
    )
    _require_stage(session, STAGE_ADDRESS_PENDING)
    settings = get_settings()
    body = (
        await _call(
            "GET",
            settings.abdm_path_enrol_suggestion,
            extra_headers={"Transaction_Id": session.abdm_txn_id},
        )
    ).body
    if not isinstance(body, dict):
        raise AbdmIdentityError("abdm_bad_response", "gateway returned a non-object body")
    suggestions = _string_list(body.get("abhaAddressList"))
    if not suggestions:
        raise AbdmIdentityError(
            "abdm_no_address_suggestions",
            "ABDM returned no ABHA address suggestions",
        )
    return suggestions


async def submit_enrolment_abha_address(
    *,
    session_id: str,
    abha_address: str,
    facility_id: str,
) -> str:
    """Bind the chosen ABHA address in the same enrolment transaction."""
    session = await otp_session.load(
        session_id, facility_id=facility_id, purpose=OtpPurpose.ENROL_BY_AADHAAR
    )
    _require_stage(session, STAGE_ADDRESS_PENDING)
    chosen = abha_address.strip()
    if not chosen or "@" not in chosen:
        raise AbdmIdentityError("abha_address_invalid", "Choose a valid ABHA address")
    settings = get_settings()
    body = (
        await _post(
            settings.abdm_path_enrol_abha_address,
            {"txnId": session.abdm_txn_id, "abhaAddress": chosen, "preferred": 1},
        )
    ).body
    if not isinstance(body, dict):
        raise AbdmIdentityError("abdm_bad_response", "gateway returned a non-object body")
    preferred = body.get("preferredAbhaAddress")
    bound = preferred.strip() if isinstance(preferred, str) and preferred.strip() else chosen
    return bound


async def fetch_abha_profile(*, profile_token: str) -> AbhaProfileView:
    settings = get_settings()
    body = (
        await _call(
            "GET",
            settings.abdm_path_profile_account,
            extra_headers={"X-token": _bearer(profile_token)},
        )
    ).body
    if not isinstance(body, dict):
        raise AbdmIdentityError("abdm_bad_response", "gateway returned a non-object body")
    kyc = body.get("kycVerified")
    return AbhaProfileView(
        abha_number=body.get("ABHANumber") if isinstance(body.get("ABHANumber"), str) else None,
        abha_address=(
            body["preferredAbhaAddress"].strip()
            if isinstance(body.get("preferredAbhaAddress"), str) and body["preferredAbhaAddress"].strip()
            else None
        ),
        name=_name(body),
        gender=body.get("gender") if isinstance(body.get("gender"), str) else None,
        status=body.get("status") if isinstance(body.get("status"), str) else None,
        kyc_verified=kyc if isinstance(kyc, bool) else None,
    )


async def fetch_abha_card(*, profile_token: str) -> AbhaCard:
    settings = get_settings()
    response = await _call(
        "GET",
        settings.abdm_path_profile_abha_card,
        extra_headers={"X-Token": _bearer(profile_token)},
        parse_json=False,
    )
    content = response.body if isinstance(response.body, bytes | bytearray) else b""
    if not content:
        raise AbdmIdentityError("abdm_no_abha_card", "ABDM returned an empty ABHA card")
    return AbhaCard(content=bytes(content), media_type="image/png")

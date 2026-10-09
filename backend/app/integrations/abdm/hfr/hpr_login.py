"""The facility manager's HPR login, which HFR registration and update require.

HFR ties a facility to the health professional who registers it, so
`basic-information` and `submit-facility` carry that person's HPR login.
NHA's M4 Postman logs in these two ways on the v4 host:

  Aadhaar OTP   POST /api/v1/auth/init {authMethod: AADHAAR_OTP, hprId}
                POST /api/v1/auth/confirmWithAadhaarOtp {otp, txnId}
  Password      POST /api/v1/auth/authPassword {hprId, password}

Each success returns an HPR token. The Aadhaar OTP login passed live on
2 October 2026. A mobile OTP is not offered: init + confirmWithMobileOTP, the
shape first guessed from the Aadhaar pair, answered 503 live, and NHA's own
mobile login is a separate v2 flow (/api/v2/auth/loginViaMobileSendOTP with an
encrypted OTP) that this module does not implement.

The token is the professional's credential. It is stored encrypted in Redis,
for the signed-in admin of this facility only, never sent to the browser,
and dropped at its own expiry or after 30 minutes, whichever is sooner.
OTPs and passwords pass straight through and are never stored or logged.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import secrets
import time
import uuid
from dataclasses import dataclass

from app.common.redis import get_redis
from app.common.security import decrypt_pii, encrypt_pii
from app.integrations.abdm.hfr import client

log = logging.getLogger(__name__)

#: An HPR ID ("name@hpr.abdm") or HPR ID number (71-1234-5678-9012).
HPR_ID = re.compile(r"^(?:[a-z0-9][a-z0-9._]{2,48}@hpr\.abdm|\d{2}-\d{4}-\d{4}-\d{4})$")
OTP_METHODS = {"AADHAAR_OTP": "/api/v1/auth/confirmWithAadhaarOtp"}
PENDING_TTL = 600
MAX_TOKEN_TTL = 1800


class HprLoginError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class HprSession:
    hpr_id: str
    hpr_id_number: str | None
    name: str | None
    expires_at: int


def _pending_key(session_id: str) -> str:
    return f"hfr:hpr-login:{session_id}"


def _token_key(facility_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"hfr:hpr-token:{facility_id}:{user_id}"


def _aad(facility_id: uuid.UUID, user_id: uuid.UUID) -> bytes:
    return f"abdm:hfr:hpr-token:{facility_id}:{user_id}".encode()


def _held_kyc_key(facility_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"hfr:hpr-held-kyc:{facility_id}:{user_id}"


def _held_kyc_aad(facility_id: uuid.UUID, user_id: uuid.UUID) -> bytes:
    return f"abdm:hfr:hpr-held-kyc:{facility_id}:{user_id}".encode()


async def hold_kyc(facility_id: uuid.UUID, user_id: uuid.UUID, *, hpr_id_number: str, kyc: dict) -> bool:
    """Give an Aadhaar KYC to this professional's HPR login. True when it
    joined a login already open for the same HPR ID number.

    An Aadhaar check that finds an existing HPID returns a token, but not an
    HPR login: it carries no roles or category, and register-professional
    refuses it ("roles or category in Hrp token can not be empty/null", live
    5 Oct 2026). If the professional is already signed in through HPR's own
    login, the KYC joins it now (live 6 Oct 2026: signed in first, then
    verified; a second OTP would have bought nothing). Otherwise it is held
    and joins the next login with the same HPR ID number."""
    sealed_login = await get_redis().get(_token_key(facility_id, user_id))
    if sealed_login:
        login = json.loads(decrypt_pii(base64.b64decode(sealed_login), associated_data=_aad(facility_id, user_id)))
        if login["expires_at"] > int(time.time()) and _claims(login["token"]).get("hprIdNumber") == hpr_id_number:
            login["kyc"] = kyc
            resealed = base64.b64encode(encrypt_pii(json.dumps(login), associated_data=_aad(facility_id, user_id)))
            await get_redis().set(
                _token_key(facility_id, user_id), resealed.decode(), ex=login["expires_at"] - int(time.time())
            )
            return True
    record = json.dumps({"hpr_id_number": hpr_id_number, "kyc": kyc})
    sealed = base64.b64encode(encrypt_pii(record, associated_data=_held_kyc_aad(facility_id, user_id)))
    await get_redis().set(_held_kyc_key(facility_id, user_id), sealed.decode(), ex=MAX_TOKEN_TTL)
    return False


async def _take_held_kyc(facility_id: uuid.UUID, user_id: uuid.UUID, hpr_id_number: object) -> dict | None:
    redis = get_redis()
    sealed = await redis.get(_held_kyc_key(facility_id, user_id))
    if not sealed:
        return None
    try:
        held = json.loads(decrypt_pii(base64.b64decode(sealed), associated_data=_held_kyc_aad(facility_id, user_id)))
    except Exception:  # noqa: BLE001 — another admin's record reads as absent
        return None
    if not isinstance(hpr_id_number, str) or held.get("hpr_id_number") != hpr_id_number:
        return None
    await redis.delete(_held_kyc_key(facility_id, user_id))
    return held.get("kyc")


def _claims(token: str) -> dict:
    """The JWT payload, for display and expiry only; HFR verifies the token."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return claims if isinstance(claims, dict) else {}
    except (IndexError, ValueError):
        return {}


def _token_from(body: object) -> str:
    token = body.get("token") if isinstance(body, dict) else None
    if not isinstance(token, str) or token.count(".") != 2:
        raise HprLoginError("hpr_login_failed", "HPR did not return a login token")
    return token


async def _keep(
    facility_id: uuid.UUID, user_id: uuid.UUID, hpr_id: str, token: str, *, kyc: dict | None = None
) -> HprSession:
    """Keep the login. `kyc` is the professional's Aadhaar KYC when HPR handed
    it over with the token (HPID creation), or the one held for this HPR ID
    number by an Aadhaar check that found an existing HPID; sealed in the same
    record, so a later login replaces both."""
    claims = _claims(token)
    # Which claims HPR put in this login, never their values: registration
    # needs roles and a category in it.
    log.warning("HPR login token carries claims %s", sorted(claims))
    if kyc is None:
        kyc = await _take_held_kyc(facility_id, user_id, claims.get("hprIdNumber"))
    now = int(time.time())
    expires_at = min(int(claims.get("exp") or now + MAX_TOKEN_TTL), now + MAX_TOKEN_TTL)
    if expires_at <= now:
        raise HprLoginError("hpr_login_failed", "HPR returned an expired login token")
    record = json.dumps({"hpr_id": hpr_id, "token": token, "expires_at": expires_at, "kyc": kyc})
    # The pool decodes replies as text, so the ciphertext is kept as base64.
    sealed = base64.b64encode(encrypt_pii(record, associated_data=_aad(facility_id, user_id)))
    await get_redis().set(_token_key(facility_id, user_id), sealed.decode(), ex=expires_at - now)
    return HprSession(
        hpr_id=str(claims.get("hprId") or hpr_id),
        hpr_id_number=claims.get("hprIdNumber") if isinstance(claims.get("hprIdNumber"), str) else None,
        name=None,
        expires_at=expires_at,
    )


async def start_otp(
    *, facility_id: uuid.UUID, user_id: uuid.UUID, hpr_id: str, method: str
) -> tuple[str, str | None]:
    if method not in OTP_METHODS:
        raise HprLoginError("hpr_method_invalid", "Choose Aadhaar OTP")
    if not HPR_ID.match(hpr_id):
        raise HprLoginError("hpr_id_invalid", "Enter an HPR ID (name@hpr.abdm) or HPR ID number")
    body = await client.call(
        "POST", "/api/v1/auth/init",
        json={"idType": "", "domainName": "", "authMethod": method, "hprId": hpr_id},
    )
    txn = body.get("transactionId") if isinstance(body, dict) else None
    if not isinstance(txn, str) or not txn:
        raise HprLoginError("hpr_login_failed", "HPR did not start the login")
    session_id = secrets.token_urlsafe(18)
    await get_redis().set(
        _pending_key(session_id),
        json.dumps({"txn": txn, "method": method, "hpr_id": hpr_id,
                    "facility_id": str(facility_id), "user_id": str(user_id)}),
        ex=PENDING_TTL,
    )
    hint = body.get("mobileNumber") if isinstance(body, dict) else None
    return session_id, hint if isinstance(hint, str) else None


async def confirm_otp(
    *, facility_id: uuid.UUID, user_id: uuid.UUID, session_id: str, otp: str
) -> HprSession:
    redis = get_redis()
    raw = await redis.get(_pending_key(session_id))
    pending = json.loads(raw) if raw else None
    if (
        not pending
        or pending.get("facility_id") != str(facility_id)
        or pending.get("user_id") != str(user_id)
    ):
        raise HprLoginError("hpr_login_session_not_found", "This HPR login has expired; start again")
    if not re.fullmatch(r"\d{6}", otp or ""):
        raise HprLoginError("hpr_otp_invalid", "Enter the 6-digit OTP")
    body = await client.call(
        "POST", OTP_METHODS[pending["method"]], json={"otp": otp, "txnId": pending["txn"]}
    )
    token = _token_from(body)
    await redis.delete(_pending_key(session_id))
    return await _keep(facility_id, user_id, pending["hpr_id"], token)


async def password_login(
    *, facility_id: uuid.UUID, user_id: uuid.UUID, hpr_id: str, password: str
) -> HprSession:
    if not HPR_ID.match(hpr_id):
        raise HprLoginError("hpr_id_invalid", "Enter an HPR ID (name@hpr.abdm) or HPR ID number")
    if not password or len(password) > 128:
        raise HprLoginError("hpr_password_invalid", "Enter the HPR password")
    body = await client.call(
        "POST", "/api/v1/auth/authPassword",
        json={"idType": "", "domainName": "", "hprId": hpr_id, "password": password},
    )
    return await _keep(facility_id, user_id, hpr_id, _token_from(body))


async def current(facility_id: uuid.UUID, user_id: uuid.UUID) -> tuple[HprSession, str] | None:
    """This admin's live HPR session and token, or None."""
    sealed = await get_redis().get(_token_key(facility_id, user_id))
    if not sealed:
        return None
    record = json.loads(
        decrypt_pii(base64.b64decode(sealed), associated_data=_aad(facility_id, user_id))
    )
    if record["expires_at"] <= int(time.time()):
        return None
    claims = _claims(record["token"])
    return (
        HprSession(
            hpr_id=str(claims.get("hprId") or record["hpr_id"]),
            hpr_id_number=claims.get("hprIdNumber") if isinstance(claims.get("hprIdNumber"), str) else None,
            name=None,
            expires_at=record["expires_at"],
        ),
        record["token"],
    )


async def kyc(facility_id: uuid.UUID, user_id: uuid.UUID) -> dict | None:
    """The Aadhaar KYC that came with this login, if HPR handed it over.
    A password or OTP login carries none: HPR returns only a token."""
    sealed = await get_redis().get(_token_key(facility_id, user_id))
    if not sealed:
        return None
    record = json.loads(
        decrypt_pii(base64.b64decode(sealed), associated_data=_aad(facility_id, user_id))
    )
    if record["expires_at"] <= int(time.time()):
        return None
    return record.get("kyc")


async def logout(facility_id: uuid.UUID, user_id: uuid.UUID) -> None:
    held = await current(facility_id, user_id)
    await get_redis().delete(_token_key(facility_id, user_id))
    if held is not None:
        try:
            await client.call("GET", "/v4/auth/logout", headers={"Authorization": held[1]})
        except Exception:  # noqa: BLE001 — the local credential is already gone
            pass

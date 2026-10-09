"""Verify the professional's official mobile and email before HPR registration.

NHA's M4 journey verifies both by OTP under the professional's HPR login
(m4-verification), then registers. HealthDoc registered without it, and HPR
answered register-professional-new with a generic 500 on every attempt
(live 6 Oct 2026). The calls, as NHA's document gives them:

  mobile  /apis/v1/doctors/generate-mobile-otp  {hpr_token, officialMobile*}
          /apis/v1/doctors/verify-mobile-otp    {hpr_token, txnId, otp*}
  email   /apis/v1/doctors/generate-verification-email  {emailAddress, otp_type: ""}
          /apis/v1/doctors/verify-email-otp     {hpr_token, hpr_id, officialEmail, emailOtp}

  * RSA-encrypted under HPR's certificate, as HPID creation sends them.

Answers are not yet seen live: their shapes are logged (keys only), and only
an answer that is not a refusal counts as verified. What was verified is kept
sealed for this admin and tied to the HPR ID number of the login it was done
under, so it never passes to another professional's registration.
"""

from __future__ import annotations

import base64
import json
import uuid

from app.common.redis import get_redis
from app.common.security import decrypt_pii, encrypt_pii
from app.integrations.abdm.hfr import hpr_login
from app.integrations.abdm.hfr.hpid import _call, _encrypt, _shape, _txn

TTL = hpr_login.MAX_TOKEN_TTL


class ContactError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _key(facility_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"hfr:hpr-contact:{facility_id}:{user_id}"


def _aad(facility_id: uuid.UUID, user_id: uuid.UUID) -> bytes:
    return f"abdm:hfr:hpr-contact:{facility_id}:{user_id}".encode()


async def _session(facility_id: uuid.UUID, user_id: uuid.UUID) -> tuple[hpr_login.HprSession, str]:
    held = await hpr_login.current(facility_id, user_id)
    if held is None or not held[0].hpr_id_number:
        raise ContactError("hpr_login_required", "Sign in to HPR as the professional first")
    return held


async def state(facility_id: uuid.UUID, user_id: uuid.UUID, hpr_id_number: str | None) -> dict:
    """What has been verified for this professional; empty for anyone else."""
    sealed = await get_redis().get(_key(facility_id, user_id))
    if not sealed:
        return {}
    try:
        record = json.loads(decrypt_pii(base64.b64decode(sealed), associated_data=_aad(facility_id, user_id)))
    except Exception:  # noqa: BLE001 — another admin's record reads as absent
        return {}
    return record if hpr_id_number and record.get("hpr_id_number") == hpr_id_number else {}


async def _save(facility_id: uuid.UUID, user_id: uuid.UUID, record: dict) -> None:
    sealed = base64.b64encode(encrypt_pii(json.dumps(record), associated_data=_aad(facility_id, user_id)))
    await get_redis().set(_key(facility_id, user_id), sealed.decode(), ex=TTL)


def public(record: dict) -> dict:
    return {
        "mobile_verified": bool(record.get("mobile_verified")),
        "mobile_hint": (record.get("mobile") or "")[-4:] or None,
        "email_verified": bool(record.get("email_verified")),
        "email": record.get("email") if record.get("email_verified") else None,
    }


async def send_mobile_otp(*, facility_id: uuid.UUID, user_id: uuid.UUID, mobile: str) -> dict:
    session, token = await _session(facility_id, user_id)
    body = await _call("generate-mobile-otp", "POST", "/apis/v1/doctors/generate-mobile-otp",
                       json={"hpr_token": token, "officialMobile": await _encrypt(mobile)})
    _shape("generate-mobile-otp", body)
    txn = _txn(body, "")
    if not txn:
        raise ContactError("hpr_otp_not_sent", "HPR did not send the mobile OTP")
    record = await state(facility_id, user_id, session.hpr_id_number) or {"hpr_id_number": session.hpr_id_number}
    record.update(mobile=mobile, mobile_txn=txn, mobile_verified=False)
    await _save(facility_id, user_id, record)
    return public(record) | {"mobile_otp_sent": True}


async def verify_mobile_otp(*, facility_id: uuid.UUID, user_id: uuid.UUID, otp: str) -> dict:
    session, token = await _session(facility_id, user_id)
    record = await state(facility_id, user_id, session.hpr_id_number)
    if not record.get("mobile_txn"):
        raise ContactError("hpr_otp_not_sent", "Send the mobile OTP first")
    body = await _call("verify-mobile-otp", "POST", "/apis/v1/doctors/verify-mobile-otp",
                       json={"hpr_token": token, "txnId": record["mobile_txn"], "otp": await _encrypt(otp)})
    _shape("verify-mobile-otp", body)
    record["mobile_verified"] = True
    await _save(facility_id, user_id, record)
    return public(record)


async def send_email_otp(*, facility_id: uuid.UUID, user_id: uuid.UUID, email: str) -> dict:
    session, _token = await _session(facility_id, user_id)
    body = await _call("generate-verification-email", "POST", "/apis/v1/doctors/generate-verification-email",
                       json={"emailAddress": email, "otp_type": ""})
    _shape("generate-verification-email", body)
    record = await state(facility_id, user_id, session.hpr_id_number) or {"hpr_id_number": session.hpr_id_number}
    record.update(email=email, email_verified=False)
    await _save(facility_id, user_id, record)
    return public(record) | {"email_otp_sent": True}


async def verify_email_otp(*, facility_id: uuid.UUID, user_id: uuid.UUID, otp: str) -> dict:
    session, token = await _session(facility_id, user_id)
    record = await state(facility_id, user_id, session.hpr_id_number)
    if not record.get("email"):
        raise ContactError("hpr_otp_not_sent", "Send the email OTP first")
    body = await _call("verify-email-otp", "POST", "/apis/v1/doctors/verify-email-otp",
                       json={"hpr_token": token, "hpr_id": session.hpr_id, "officialEmail": record["email"],
                             "emailOtp": int(otp)})
    _shape("verify-email-otp", body)
    record["email_verified"] = True
    await _save(facility_id, user_id, record)
    return public(record)

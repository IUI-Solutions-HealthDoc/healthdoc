"""Create an HPID for a health professional (M4 HPR-002 to 011).

NHA's v4 flow, as the sandbox answered it on 5 October 2026:

  generateLink        -> {status: "URL GENERATED", txnId, url}
                         The professional authenticates with Aadhaar on NHA's
                         own page (healthidbeta.abdm.gov.in): the Aadhaar
                         number and its OTP never pass through HealthDoc.
  isAuthenticated     -> a bare false until they finish there, then true.
  verifyOTP {txnId}   -> the Aadhaar KYC; before authentication NHA refuses
                         it (HIS-2099 "Aadhaar verification is pending").
  checkHpIdAccountExist  an Aadhaar that already holds an HPID logs in instead.
  hpid/suggestion     -> HPR IDs to choose from.
  demographicAuthViaMobile, then generateMobileOTP / verifyMobileOTP when the
                         communication mobile is not the Aadhaar-linked one.
  createHprIdWithPreVerified -> the HPR token and HPR ID number.

The mobile number, OTP, email and password travel RSA-encrypted under HPR's
own certificate (GET /api/v1/auth/cert, a bare PEM with no algorithm named),
as NHA's Postman sends them. OAEP with SHA-1 is ABDM's published padding for
the ABHA service; that HPR uses the same is NOT yet confirmed live.

Response shapes after verifyOTP are unconfirmed: each step logs the keys it
received, never the values, and reads fields permissively. The session is
held in Redis, encrypted, for the signed-in admin only, for 15 minutes.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import secrets
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.common.redis import get_redis
from app.common.security import decrypt_pii, encrypt_pii
from app.integrations.abdm.client import AbdmError, AbdmRejected
from app.integrations.abdm.hfr import client, hpr_login

log = logging.getLogger("healthdoc.abdm")
SESSION_TTL = 900
#: HPR's rule, quoted in NHA's Postman: a lower and an upper case letter, a
#: special character, at least 8 characters. HPR checks the rest (no runs, no
#: first or last name).
PASSWORD = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*[^A-Za-z0-9]).{8,64}$")
HPR_ID_LOCAL = re.compile(r"^[a-z0-9][a-z0-9._]{3,47}$")


class HpidError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _key(session_id: str) -> str:
    return f"hpr:hpid:{session_id}"


def _aad(session_id: str, facility_id: uuid.UUID, user_id: uuid.UUID) -> bytes:
    return f"abdm:hpr:hpid:{session_id}:{facility_id}:{user_id}".encode()


async def _save(session_id: str, facility_id: uuid.UUID, user_id: uuid.UUID, state: dict) -> None:
    sealed = encrypt_pii(json.dumps(state), associated_data=_aad(session_id, facility_id, user_id))
    await get_redis().set(_key(session_id), base64.b64encode(sealed).decode(), ex=SESSION_TTL)


async def _load(session_id: str, facility_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    raw = await get_redis().get(_key(session_id))
    if not raw:
        raise HpidError("hpid_session_not_found", "This HPID creation has expired; start again")
    try:
        plain = decrypt_pii(base64.b64decode(raw), associated_data=_aad(session_id, facility_id, user_id))
    except Exception:  # noqa: BLE001 — another admin's session reads as absent
        raise HpidError("hpid_session_not_found", "This HPID creation has expired; start again") from None
    return json.loads(plain)


async def _call(step: str, method: str, path: str, *, json: dict | None = None) -> object:
    """One HPR call. A failure is logged with the step, HPR's status and its
    own HIS codes and field names, never the values sent or received."""
    try:
        return await client.call(method, path, json=json)
    except AbdmError as exc:
        codes = list(exc.error_codes)
        if isinstance(exc, AbdmRejected) and isinstance(exc.detail, dict):
            codes += [str(d.get("code")) for d in exc.detail.get("details") or [] if isinstance(d, dict) and d.get("code")]
            codes.append(str(exc.detail.get("code") or ""))
        log.warning("HPR %s failed: %s status=%s codes=%s shape=%s",
                    step, type(exc).__name__, exc.status_code, [c for c in codes if c], exc.body_shape)
        raise


def _shape(step: str, body: object) -> None:
    """Learn the answer's shape without logging what it says."""
    keys = sorted(body) if isinstance(body, dict) else type(body).__name__
    # Warning, not info, until HPR's shapes are confirmed: INFO is filtered
    # on the running stack, and the field names are what a live run needs.
    log.warning("HPR %s answered with %s", step, keys)


def _txn(body: object, current: str) -> str:
    # A step may hand on a new transaction id; the next call wants the latest.
    new = body.get("txnId") if isinstance(body, dict) else None
    return new if isinstance(new, str) and new else current


async def _encrypt(value: str) -> str:
    pem = await _call("cert", "GET", "/api/v1/auth/cert")
    if not isinstance(pem, str) or "BEGIN PUBLIC KEY" not in pem:
        raise HpidError("hpid_certificate_unavailable", "HPR did not return its encryption certificate")
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, rsa.RSAPublicKey):
        raise HpidError("hpid_certificate_unavailable", "HPR's certificate is not an RSA key")
    sealed = key.encrypt(
        value.encode(), padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None)
    )
    return base64.b64encode(sealed).decode()


def _kyc(body: dict) -> dict:
    """The Aadhaar KYC, read permissively: the field names are unconfirmed."""
    def pick(*names: str) -> str:
        for name in names:
            value = body.get(name)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
        return ""

    first, middle, last = pick("firstName"), pick("middleName"), pick("lastName")
    full = pick("name", "fullName")
    if not first and full:
        parts = full.split()
        first, last = parts[0], " ".join(parts[1:]) if len(parts) > 1 else ""
        middle = ""
    return {
        "name": full or " ".join(p for p in (first, middle, last) if p),
        "first_name": first,
        "middle_name": middle,
        "last_name": last,
        "gender": pick("gender"),
        "birth_date": pick("birthdate", "dateOfBirth", "dob"),
        "year_of_birth": pick("yearOfBirth"),
        "address": pick("address"),
        "state_name": pick("stateName", "state"),
        "district_name": pick("districtName", "district"),
        "pincode": pick("pincode"),
        "mobile": pick("mobile", "mobileNumber"),
        "email": pick("email"),
        "photo": pick("photo", "kycPhoto", "profilePhoto"),
    }


async def start(*, facility_id: uuid.UUID, user_id: uuid.UUID) -> tuple[str, str]:
    """HPR-002: open NHA's Aadhaar page. Returns (session id, page URL)."""
    body = await _call("generateLink", "POST", "/aadhaar/generateLink", json={"scopes": ["nhpr-register"], "source": "NHPR"})
    _shape("generateLink", body)
    txn = body.get("txnId") if isinstance(body, dict) else None
    url = body.get("url") if isinstance(body, dict) else None
    if not isinstance(txn, str) or not txn or not isinstance(url, str) or not url.startswith("https://"):
        raise HpidError("hpid_start_failed", "HPR did not open an Aadhaar verification page")
    session_id = secrets.token_urlsafe(18)
    await _save(session_id, facility_id, user_id, {"txn": txn, "stage": "aadhaar"})
    return session_id, url


async def check(*, facility_id: uuid.UUID, user_id: uuid.UUID, session_id: str) -> dict:
    """After the professional finishes on NHA's page: their KYC, whether they
    already hold an HPID, and HPR ID suggestions. Before then: waiting."""
    state = await _load(session_id, facility_id, user_id)
    if state["stage"] == "aadhaar":
        authenticated = await _call("isAuthenticated", "POST", "/aadhaar/isAuthenticated", json={"txnId": state["txn"]})
        if authenticated is not True:
            return {"authenticated": False}
        body = await _call("verifyOTP", "POST", "/v2/registration/aadhaar/verifyOTP", json={"txnId": state["txn"]})
        _shape("verifyOTP", body)
        if not isinstance(body, dict):
            raise HpidError("hpid_kyc_failed", "HPR did not return the Aadhaar details")
        state.update(txn=_txn(body, state["txn"]), kyc=_kyc(body), stage="verified")

        exists = await _call("checkHpIdAccountExist", "POST", "/v1/registration/aadhaar/checkHpIdAccountExist", json={"txnId": state["txn"]})
        _shape("checkHpIdAccountExist", exists)
        existing = None
        if isinstance(exists, dict):
            existing = exists.get("hprIdNumber") or exists.get("hprId")
            state["txn"] = _txn(exists, state["txn"])
        if existing and exists.get("new") is not True:
            # HPR-002: one HPID per Aadhaar. Sign in with it instead.
            await get_redis().delete(_key(session_id))
            return {"authenticated": True, "existing_hpr_id": str(existing)}

        suggestions = await _call("suggestion", "POST", "/v1/registration/aadhaar/hpid/suggestion", json={"txnId": state["txn"]})
        _shape("suggestion", suggestions)
        state["suggestions"] = [s for s in suggestions if isinstance(s, str)][:10] if isinstance(suggestions, list) else []
        await _save(session_id, facility_id, user_id, state)
    kyc = state["kyc"]
    return {
        "authenticated": True,
        "kyc": {k: v for k, v in kyc.items() if k != "mobile"},
        "aadhaar_mobile_hint": kyc["mobile"][-4:] if kyc["mobile"] else None,
        "suggestions": state.get("suggestions", []),
        "mobile_verified": state.get("mobile_verified", False),
    }


async def verify_mobile(*, facility_id: uuid.UUID, user_id: uuid.UUID, session_id: str, mobile: str) -> dict:
    """HPR-010: is the communication mobile the Aadhaar-linked one? If not,
    HPR sends it an OTP (HPR-011)."""
    state = await _load(session_id, facility_id, user_id)
    if state["stage"] != "verified":
        raise HpidError("hpid_not_verified", "Finish the Aadhaar verification first")
    body = await _call("demographicAuthViaMobile", "POST", "/v2/registration/aadhaar/demographicAuthViaMobile",
        json={"txnId": state["txn"], "mobileNumber": await _encrypt(mobile)},
    )
    _shape("demographicAuthViaMobile", body)
    state["txn"] = _txn(body, state["txn"])
    state["mobile"] = mobile
    matched = isinstance(body, dict) and (body.get("verified") is True or body.get("status") in (True, "true", "SUCCESS"))
    if matched:
        state["mobile_verified"] = True
        await _save(session_id, facility_id, user_id, state)
        return {"mobile_verified": True, "otp_sent": False}
    sent = await _call("generateMobileOTP", "POST", "/v1/registration/aadhaar/generateMobileOTP", json={"mobile": mobile, "txnId": state["txn"]})
    _shape("generateMobileOTP", sent)
    state["txn"] = _txn(sent, state["txn"])
    await _save(session_id, facility_id, user_id, state)
    return {"mobile_verified": False, "otp_sent": True}


async def confirm_mobile(*, facility_id: uuid.UUID, user_id: uuid.UUID, session_id: str, otp: str) -> dict:
    state = await _load(session_id, facility_id, user_id)
    if not state.get("mobile"):
        raise HpidError("hpid_mobile_missing", "Enter the mobile number first")
    if not re.fullmatch(r"\d{6}", otp or ""):
        raise HpidError("hpid_otp_invalid", "Enter the 6-digit OTP")
    body = await _call("verifyMobileOTP", "POST", "/v1/registration/aadhaar/verifyMobileOTP",
        json={"otp": await _encrypt(otp), "txnId": state["txn"]},
    )
    _shape("verifyMobileOTP", body)
    state["txn"] = _txn(body, state["txn"])
    state["mobile_verified"] = True
    await _save(session_id, facility_id, user_id, state)
    return {"mobile_verified": True}


async def create(
    *, facility_id: uuid.UUID, user_id: uuid.UUID, session_id: str, hpr_id: str, email: str,
    password: str, category_code: int, subcategory_code: int, state_code: str, district_code: str,
) -> tuple[hpr_login.HprSession, str]:
    """HPR-011: create the HPID. Its token signs the professional in, so HPR
    registration can follow under it (HPR-018). Returns (session, HPR ID number)."""
    state = await _load(session_id, facility_id, user_id)
    if not state.get("mobile_verified"):
        raise HpidError("hpid_mobile_unverified", "Verify the communication mobile first")
    if not HPR_ID_LOCAL.match(hpr_id):
        raise HpidError("hpid_id_invalid", "An HPR ID is 4 to 48 lower-case letters, digits, dots or underscores")
    kyc = state["kyc"]
    if not PASSWORD.match(password) or any(
        part and part.lower() in password.lower() for part in (kyc["first_name"], kyc["last_name"])
    ):
        raise HpidError("hpid_password_invalid",
                        "Use 8 or more characters with upper and lower case letters and a special character, "
                        "not containing your first or last name")
    body = await _call("createHprIdWithPreVerified", "POST", "/v2/registration/aadhaar/createHprIdWithPreVerified",
        json={
            "txnId": state["txn"],
            "email": await _encrypt(email),
            "idType": "hpr_id",
            "domainName": "@hpr.abdm",
            "firstName": kyc["first_name"],
            "middleName": kyc["middle_name"],
            "lastName": kyc["last_name"],
            "password": await _encrypt(password),
            "profilePhoto": kyc["photo"],
            "hprId": hpr_id,
            "sourceType": "AADHAAR",
            "hpCategoryCode": category_code,
            "hpSubCategoryCode": subcategory_code,
            "clientId": "",
            "stateCode": state_code,
            "districtCode": district_code,
            # NHA's example; the meaning of role 3 is not published.
            "role": 3,
        },
    )
    _shape("createHprIdWithPreVerified", body)
    token = body.get("token") if isinstance(body, dict) else None
    number = body.get("hprIdNumber") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token or not isinstance(number, str):
        raise HpidError("hpid_create_failed", "HPR did not create the HPID")
    await get_redis().delete(_key(session_id))
    created = body.get("hprId") if isinstance(body.get("hprId"), str) else f"{hpr_id}@hpr.abdm"
    session = await hpr_login._keep(facility_id, user_id, created, token)
    return session, number

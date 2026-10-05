"""Create an HPID for a health professional (M4 HPR-002 to 011).

NHA's link flow, the one integrators use (5 Oct 2026): the professional
verifies their Aadhaar (consent, number, OTP) on NHA's own page, so the
Aadhaar number never passes through HealthDoc.

  /aadhaar/generateLink       -> {status: "URL GENERATED", txnId, url}
  /aadhaar/isAuthenticated    -> a bare false until they finish on NHA's page
  /v2/registration/aadhaar/verifyOTP {txnId}  -> the Aadhaar KYC
  /v1/registration/aadhaar/checkHpIdAccountExist {txnId}
        -> the KYC again; for an Aadhaar that already holds an HPID, also its
        token and HPR ID number, which sign the professional in
  /v1/registration/aadhaar/hpid/suggestion          -> HPR IDs to offer
  /v2/registration/aadhaar/demographicAuthViaMobile -> {verified}; when false,
  /v1/registration/aadhaar/generateMobileOTP + verifyMobileOTP (HPR-010/011)
  /v2/registration/aadhaar/createHprIdWithPreVerified -> token, HPR ID number, KYC

NHA's in-app Aadhaar OTP (generateOtp / verifyOTP with an OTP) is not used:
in the sandbox its verify cannot find the transaction its generate made.

Mobile, OTP, email and password travel RSA-encrypted under HPR's own
certificate (GET /api/v1/auth/cert) with PKCS#1 v1.5 padding, NHA's
"RSA/ECB/PKCS1Padding" (OAEP and plain text get HIS-500, 5 Oct live).

The KYC that HPR returns travels with the professional's HPR login
(hpr_login), which is how registration in HPR gets their Aadhaar details
without asking the browser. Each step logs the field names of HPR's answer,
never a value.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import secrets
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.common.redis import get_redis
from app.common.security import decrypt_pii, encrypt_pii
from app.integrations.abdm.client import AbdmError, AbdmRejected
from app.integrations.abdm.hfr import client, hpr_login

log = logging.getLogger("healthdoc.abdm")
SESSION_TTL = 900
#: HPR's rule, quoted in NHA's Postman: a lower and an upper case letter, a
#: special character, at least 8 characters. HPR checks the rest.
PASSWORD = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*[^A-Za-z0-9]).{8,64}$")
HPR_ID_LOCAL = re.compile(r"^[a-z0-9][a-z0-9._]{3,47}$")
#: NHA's role codes for createHprIdWithPreVerified (register document, s.4).
ROLES = {"PROFESSIONAL": 1, "FACILITY_MANAGER": 2, "BOTH": 3}
VERIFY_OTP = "/v2/registration/aadhaar/verifyOTP"


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
        codes, reasons = list(exc.error_codes), []
        if isinstance(exc, AbdmRejected) and isinstance(exc.detail, dict):
            details = [d for d in exc.detail.get("details") or [] if isinstance(d, dict)]
            codes += [str(d.get("code")) for d in details if d.get("code")]
            codes.append(str(exc.detail.get("code") or ""))
            # HPR's own reasons are fixed texts ("Invalid OTP", "Failed to retrieve
            # aadhaar transaction details for txnID - <uuid>"); no value we sent.
            reasons = [str(d.get("message"))[:160] for d in details if d.get("message")]
        log.warning("HPR %s failed: %s status=%s codes=%s reasons=%s shape=%s",
                    step, type(exc).__name__, exc.status_code, [c for c in codes if c], reasons, exc.body_shape)
        raise


def _shape(step: str, body: object) -> None:
    """Learn the answer's shape without logging what it says."""
    keys = sorted(body) if isinstance(body, dict) else type(body).__name__
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
    return base64.b64encode(key.encrypt(value.encode(), padding.PKCS1v15())).decode()


def _text(body: dict, *names: str) -> str:
    for name in names:
        value = body.get(name)
        if isinstance(value, str | int) and not isinstance(value, bool) and str(value).strip():
            return str(value).strip()
    return ""


def kyc_from(*bodies: object) -> dict:
    """The Aadhaar KYC from any of HPR's answers that carry it (verifyOTP,
    checkHpIdAccountExist, createHprIdWithPreVerified). Earlier answers win;
    later ones fill what they lacked. The address comes as a string
    (production document) or as an object (sandbox document); both are read."""
    kyc = {k: "" for k in ("name", "first_name", "middle_name", "last_name", "gender", "birth_date",
                           "address", "state_name", "district_name", "pincode", "mobile", "email", "photo",
                           "state_code", "district_code")}
    for body in bodies:
        if not isinstance(body, dict):
            continue
        found = {
            "name": _text(body, "name", "fullName"),
            "first_name": _text(body, "firstName"),
            "middle_name": _text(body, "middleName"),
            "last_name": _text(body, "lastName"),
            "gender": _text(body, "gender")[:1].upper(),
            "state_name": _text(body, "stateName"),
            "district_name": _text(body, "districtName"),
            "pincode": _text(body, "pincode"),
            "mobile": _text(body, "mobile", "mobileNumber"),
            "email": _text(body, "email"),
            "photo": _text(body, "kycPhoto", "profilePhoto", "photo"),
            "state_code": _text(body, "stateCode"),
            "district_code": _text(body, "districtCode"),
        }
        day, month, year = _text(body, "dayOfBirth"), _text(body, "monthOfBirth"), _text(body, "yearOfBirth")
        dob = _text(body, "dob", "dateOfBirth", "birthdate")
        found["birth_date"] = (f"{year}-{month.zfill(2)}-{day.zfill(2)}" if day and month and year
                               else dob if re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob) else "")
        address = body.get("address")
        if isinstance(address, dict):
            parts = [str(address.get(k)).strip() for k in
                     ("house", "street", "landmark", "locality", "vtc", "subdistrict", "district", "state")
                     if isinstance(address.get(k), str | int) and str(address.get(k)).strip()]
            found["address"] = ", ".join(parts)
            found["pincode"] = found["pincode"] or _text(address, "pincode")
        elif isinstance(address, str):
            found["address"] = address.strip()
        if found["mobile"].startswith("*"):
            found["mobile"] = ""  # a masked mobile is no use to registration
        for key, value in found.items():
            if value and not kyc[key]:
                kyc[key] = value
    if not kyc["first_name"] and kyc["name"]:
        parts = kyc["name"].split()
        kyc["first_name"], kyc["last_name"] = parts[0], " ".join(parts[1:])
    if not kyc["name"]:
        kyc["name"] = " ".join(p for p in (kyc["first_name"], kyc["middle_name"], kyc["last_name"]) if p)
    return kyc


def public(kyc: dict) -> dict:
    """What the desk may see: no full mobile."""
    shown = {k: v for k, v in kyc.items() if k != "mobile"}
    shown["mobile_hint"] = kyc["mobile"][-4:] if kyc.get("mobile") else None
    return shown


async def _after_aadhaar(state: dict, verified: object, *, facility_id: uuid.UUID, user_id: uuid.UUID,
                         session_id: str) -> dict:
    """Once Aadhaar is verified: the KYC, an existing HPID's login, or HPR ID
    suggestions for a new one."""
    exists = await _call("checkHpIdAccountExist", "POST", "/v1/registration/aadhaar/checkHpIdAccountExist",
                         json={"txnId": state["txn"]})
    _shape("checkHpIdAccountExist", exists)
    state["txn"] = _txn(exists, state["txn"])
    kyc = kyc_from(verified, exists)

    number = _text(exists, "hprIdNumber") if isinstance(exists, dict) else ""
    token = _text(exists, "token") if isinstance(exists, dict) else ""
    if number:
        # HPR-002: one HPID per person. HPR returned theirs and, with it, a
        # login: sign them in, carrying the KYC registration will need.
        await get_redis().delete(_key(session_id))
        if not token:
            return {"existing": True, "hpr_id_number": number, "signed_in": False, "kyc": public(kyc)}
        hpr_id = _text(exists, "hprId") or number
        session = await hpr_login._keep(facility_id, user_id, hpr_id, token, kyc=kyc)
        return {"existing": True, "hpr_id": session.hpr_id, "hpr_id_number": number, "signed_in": True,
                "kyc": public(kyc)}

    suggestions = await _call("suggestion", "POST", "/v1/registration/aadhaar/hpid/suggestion",
                              json={"txnId": state["txn"]})
    _shape("suggestion", suggestions)
    state.update(stage="verified", kyc=kyc, mobile_verified=False,
                 suggestions=[s for s in suggestions if isinstance(s, str)][:10] if isinstance(suggestions, list) else [])
    await _save(session_id, facility_id, user_id, state)
    return {"existing": False, "kyc": public(kyc), "suggestions": state["suggestions"], "mobile_verified": False}


def _open_key(facility_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"hpr:hpid:open:{facility_id}:{user_id}"


async def start_link(*, facility_id: uuid.UUID, user_id: uuid.UUID, fresh: bool = False) -> tuple[str, str]:
    """HPR-002 to 007, on NHA's own page: it collects the consent, the Aadhaar
    number, a captcha and the OTP. Returns (session id, page URL).

    An admin's attempt still waiting on NHA's page is handed back rather than
    replaced: the desk forgets it on a reload, and NHA confirms only the link
    the professional actually used (5 Oct 2026, a second link read false while
    the first read true). fresh=True, after Cancel, opens a new one."""
    if not fresh:
        open_id = await get_redis().get(_open_key(facility_id, user_id))
        if open_id:
            open_id = open_id.decode() if isinstance(open_id, bytes) else open_id
            try:
                state = await _load(open_id, facility_id, user_id)
            except HpidError:
                state = {}
            if state.get("stage") == "link" and state.get("url"):
                return open_id, state["url"]
    body = await _call("generateLink", "POST", "/aadhaar/generateLink", json={"scopes": ["nhpr-register"], "source": "NHPR"})
    _shape("generateLink", body)
    txn = body.get("txnId") if isinstance(body, dict) else None
    url = body.get("url") if isinstance(body, dict) else None
    if not isinstance(txn, str) or not txn or not isinstance(url, str) or not url.startswith("https://"):
        raise HpidError("hpid_start_failed", "HPR did not open an Aadhaar verification page")
    session_id = secrets.token_urlsafe(18)
    await _save(session_id, facility_id, user_id, {"txn": txn, "stage": "link", "url": url})
    await get_redis().set(_open_key(facility_id, user_id), session_id, ex=SESSION_TTL)
    return session_id, url


async def check_link(*, facility_id: uuid.UUID, user_id: uuid.UUID, session_id: str) -> dict:
    """After the professional finishes on NHA's page: their KYC, and either an
    existing HPID's login or HPR ID suggestions. Before then:
    {"authenticated": False}."""
    state = await _load(session_id, facility_id, user_id)
    if state["stage"] != "link":
        raise HpidError("hpid_not_waiting", "This Aadhaar verification is already done")
    authenticated = await _call("isAuthenticated", "POST", "/aadhaar/isAuthenticated", json={"txnId": state["txn"]})
    if authenticated is not True:
        # Only a bare true has been seen; anything else would read as "not yet" forever.
        if authenticated is not False:
            _shape("isAuthenticated", authenticated)
        return {"authenticated": False}
    verified = await _call("verifyOTP", "POST", VERIFY_OTP, json={"txnId": state["txn"]})
    _shape("verifyOTP", verified)
    state["txn"] = _txn(verified, state["txn"])
    return {"authenticated": True} | await _after_aadhaar(
        state, verified, facility_id=facility_id, user_id=user_id, session_id=session_id)


async def verify_mobile(*, facility_id: uuid.UUID, user_id: uuid.UUID, session_id: str, mobile: str) -> dict:
    """HPR-010: is the communication mobile the Aadhaar-linked one? If not,
    HPR sends it an OTP (HPR-011). Calling again with another number corrects
    a mistyped one."""
    state = await _load(session_id, facility_id, user_id)
    if state["stage"] != "verified":
        raise HpidError("hpid_not_verified", "Verify the Aadhaar on NHA's page first")
    body = await _call("demographicAuthViaMobile", "POST", "/v2/registration/aadhaar/demographicAuthViaMobile",
                       json={"txnId": state["txn"], "mobileNumber": await _encrypt(mobile)})
    _shape("demographicAuthViaMobile", body)
    state["txn"] = _txn(body, state["txn"])
    state["mobile"] = mobile
    state["mobile_verified"] = False
    if isinstance(body, dict) and body.get("verified") is True:
        state["mobile_verified"] = True
        await _save(session_id, facility_id, user_id, state)
        return {"mobile_verified": True, "otp_sent": False}
    sent = await _call("generateMobileOTP", "POST", "/v1/registration/aadhaar/generateMobileOTP",
                       json={"mobile": mobile, "txnId": state["txn"]})
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
                       json={"otp": await _encrypt(otp), "txnId": state["txn"]})
    _shape("verifyMobileOTP", body)
    state["txn"] = _txn(body, state["txn"])
    state["mobile_verified"] = True
    await _save(session_id, facility_id, user_id, state)
    return {"mobile_verified": True}


def kyc_as_answer(kyc: dict) -> dict:
    """A kept KYC in HPR's own field names, so kyc_from can merge it."""
    return {"firstName": kyc.get("first_name"), "middleName": kyc.get("middle_name"),
            "lastName": kyc.get("last_name"), "name": kyc.get("name"), "gender": kyc.get("gender"),
            "dob": kyc.get("birth_date"), "address": kyc.get("address"), "stateName": kyc.get("state_name"),
            "districtName": kyc.get("district_name"), "pincode": kyc.get("pincode"), "kycPhoto": kyc.get("photo"),
            "stateCode": kyc.get("state_code"), "districtCode": kyc.get("district_code"),
            "mobile": kyc.get("mobile"), "email": kyc.get("email")}


async def create(
    *, facility_id: uuid.UUID, user_id: uuid.UUID, session_id: str, hpr_id: str, email: str,
    password: str, category_code: int, subcategory_code: int, state_code: str, district_code: str,
    role: str = "PROFESSIONAL",
) -> tuple[hpr_login.HprSession, str]:
    """HPR-011: create the HPID. Its token and the KYC sign the professional
    in, so HPR registration (HPR-018) follows. Returns (session, HPR ID number).
    `state_code` and `district_code` are HPR's ISO (LGD) codes."""
    state = await _load(session_id, facility_id, user_id)
    if state.get("stage") != "verified" or not state.get("mobile_verified"):
        raise HpidError("hpid_mobile_unverified", "Verify the communication mobile first")
    if not HPR_ID_LOCAL.match(hpr_id):
        raise HpidError("hpid_id_invalid", "An HPR ID is 4 to 48 lower-case letters, digits, dots or underscores")
    kyc = state["kyc"]
    if not PASSWORD.match(password) or any(
        part and part.lower() in password.lower() for part in (kyc["first_name"], kyc["last_name"])
    ):
        raise HpidError("hpid_password_invalid",
                        "Use 8 or more characters with upper and lower case letters and a special character, "
                        "not containing their first or last name")
    body = await _call("createHprIdWithPreVerified", "POST", "/v2/registration/aadhaar/createHprIdWithPreVerified", json={
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
        "role": ROLES[role],
    })
    _shape("createHprIdWithPreVerified", body)
    token = body.get("token") if isinstance(body, dict) else None
    number = body.get("hprIdNumber") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token or not isinstance(number, str):
        raise HpidError("hpid_create_failed", "HPR did not create the HPID")
    await get_redis().delete(_key(session_id))
    created = body.get("hprId") if isinstance(body.get("hprId"), str) else f"{hpr_id}@hpr.abdm"
    merged = kyc_from(kyc_as_answer(kyc), body, {"mobile": state.get("mobile", ""), "email": email})
    session = await hpr_login._keep(facility_id, user_id, created, token, kyc=merged)
    return session, number

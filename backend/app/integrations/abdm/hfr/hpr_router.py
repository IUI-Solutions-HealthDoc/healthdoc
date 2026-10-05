"""Healthcare Professionals Registry for the facility administrator (ABDM M4, HPR).

HPR's master data, HPID creation in HealthDoc (HPR-002 to 011) and
registration of the signed-in professional (HPR-018 to 079). Master lists come back
as {code, label}; HPR's own field names differ per list. HPR's state and
district ids are its own, not LGD codes (district/27 is Punjab, 5 Oct live),
so every HPR form takes them from these lists only.
"""

from __future__ import annotations

import base64
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.audit.service import write_audit_log
from app.auth.deps import CurrentDbUser, require_roles
from app.common import captcha
from app.common.db import get_db
from app.integrations.abdm.client import AbdmAuthError, AbdmNotConfigured, AbdmRejected, AbdmUnavailable
from app.integrations.abdm.hfr import client, hpid, hpr_login, hpr_registration
from app.integrations.abdm.hfr.router import _hfr

router = APIRouter(
    prefix="/abdm/hpr",
    tags=["abdm"],
    dependencies=[Depends(require_roles("admin"))],
)

_ID = r"^\d{1,8}$"


def _list(body: object) -> list[dict]:
    if not isinstance(body, list):
        raise HTTPException(502, {"code": "hpr_bad_response", "message": "HPR returned an unexpected list"})
    return [row for row in body if isinstance(row, dict)]


def _options(body: object, label: str, code: str = "id") -> list[dict]:
    return [
        {"code": str(row[code]), "label": str(row[label]).strip()}
        for row in _list(body)
        if row.get(code) is not None and isinstance(row.get(label), str)
    ]


# ----------------------------------------------------------------- master data


@router.get("/master/categories")
async def categories() -> dict:
    """HPR-054/055: professional categories, each with its subcategories."""
    rows = _list(await _hfr(client.call("GET", "/hpid/get/categories?role=1")))
    return {"data": [
        {"code": str(row["code"]), "label": str(row.get("name", "")).strip(),
         "subcategories": [{"code": str(sub["code"]), "label": str(sub.get("name", "")).strip()}
                           for sub in row.get("subCategories") or [] if isinstance(sub, dict) and "code" in sub]}
        for row in rows if "code" in row
    ]}


@router.get("/master/states")
async def states() -> dict:
    return {"data": _options(await _hfr(client.call("GET", "/apis/v1/masters/states")), "name")}


@router.get("/master/districts")
async def districts(state_code: Annotated[str, Query(pattern=_ID)]) -> dict:
    return {"data": _options(await _hfr(client.call("GET", f"/apis/v1/masters/district/{state_code}")), "districtName")}


@router.get("/master/sub-districts")
async def sub_districts(district_code: Annotated[str, Query(pattern=_ID)]) -> dict:
    body = await _hfr(client.call("GET", f"/apis/v1/masters/sub-districts/{district_code}"))
    return {"data": _options(body, "subDistrictName")}


@router.get("/master/countries")
async def countries() -> dict:
    return {"data": _options(await _hfr(client.call("GET", "/apis/v1/masters/countries")), "enShortName")}


@router.get("/master/languages")
async def languages() -> dict:
    return {"data": _options(await _hfr(client.call("GET", "/apis/v1/masters/languages")), "name")}


@router.get("/master/systems-of-medicine")
async def systems_of_medicine() -> dict:
    rows = _list(await _hfr(client.call("GET", "/apis/v1/masters/system-of-medicines")))
    return {"data": [
        {"code": str(row["id"]), "label": str(row.get("medicalSystem", "")).strip(), "hpr_type": row.get("hprType")}
        for row in rows if "id" in row
    ]}


@router.get("/master/councils")
async def councils(kind: Literal["medical", "nurse"] = "medical") -> dict:
    """HPR-056: the council the registration is with."""
    rows = _list(await _hfr(client.call("GET", f"/apis/v1/masters/{kind}-councils")))
    return {"data": [
        {"code": str(row["id"]), "label": str(row.get("name", "")).strip(),
         "state_id": str(row["stateId"]) if row.get("stateId") is not None else None,
         "system_of_medicine_id": row.get("systemOfMedicineId")}
        for row in rows if "id" in row and row.get("status", True)
    ]}


@router.get("/master/courses")
async def courses(
    system_of_medicine: Annotated[str, Query(min_length=1, max_length=120)],
    hpr_type: Literal["doctor", "nurse", "pharmacist"] = "doctor",
    all_courses: bool = False,
) -> dict:
    """HPR-062. HPR returns only basic degrees for an empty qualification
    count and every course (PG included) for "1" (5 Oct live)."""
    body = await _hfr(client.call("POST", "/apis/v1/masters/courses", json={
        "systemOfMedicine": system_of_medicine, "hprType": hpr_type, "qualificationCount": "1" if all_courses else ""}))
    return {"data": _options(body, "name")}


@router.get("/master/colleges")
async def colleges(
    state_code: Annotated[str, Query(pattern=_ID)],
    system_of_medicine: Annotated[str, Query(min_length=1, max_length=120)],
) -> dict:
    """HPR-065. HPR keys colleges by state and system-of-medicine name."""
    path = f"/apis/v1/masters/colleges/{state_code}/{quote(system_of_medicine, safe='')}"
    return {"data": _options(await _hfr(client.call("GET", path)), "name")}


@router.get("/master/universities")
async def universities(college_code: Annotated[str, Query(pattern=_ID)]) -> dict:
    """HPR-066: the universities a college is affiliated to."""
    return {"data": _options(await _hfr(client.call("GET", f"/apis/v1/masters/universites/{college_code}")), "name")}


# ----------------------------------------------------------------- HPID creation, in HealthDoc (HPR-002 to 011)

#: NHA's HPID consent, word for word from its Aadhaar gateway (5 Oct 2026).
#: HPR-003 requires the professional to read and accept it.
HPID_CONSENT_VERSION = "nha-hpid-consent-2026-10-05"
HPID_CONSENT_TEXT = (
    "I, hereby declare that I am voluntarily sharing my Aadhaar Number / Virtual ID and demographic information "
    "issued by UIDAI, with National Health Authority (NHA) for the sole purpose of creation of Healthcare "
    "Professional ID. I understand that my Healthcare Professional ID can be used and shared for purposes as may "
    "be notified by Ayushman Bharat Digital Mission (ABDM) from time to time including provision of healthcare "
    "services. Further, I am aware that my personal identifiable information (Name, Address, Age, Date of Birth, "
    "Gender and Photograph) may be made available to the entities working in the National Digital Health "
    "Ecosystem (NDHE) which inter alia includes stakeholders and entities such as healthcare professional (e.g. "
    "doctors), facilities (e.g. hospitals, laboratories) and data fiduciaries (e.g. health programmes), which are "
    "registered with or linked to the Ayushman Bharat Digital Mission (ABDM), and various processes there under. "
    "I authorize NHA to use my Aadhaar number / Virtual ID for performing Aadhaar based authentication with UIDAI "
    "as per the provisions of the Aadhaar (Targeted Delivery of Financial and other Subsidies, Benefits and "
    "Services) Act, 2016 for the aforesaid purpose. I understand that UIDAI will share my e-KYC details, or "
    "response of “Yes” with NHA upon successful authentication. I consciously choose to use Aadhaar "
    "number / Virtual ID for the purpose of availing benefits across the NDHE. I am aware that my personal "
    "identifiable information excluding Aadhaar number / VID number can be used and shared for purposes as "
    "mentioned above. I reserve the right to revoke the given consent at any point of time as per provisions of "
    "Aadhar Act and Regulations and other laws, rules and regulations."
)
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _refused(exc: hpid.HpidError) -> HTTPException:
    status = 404 if exc.code == "hpid_session_not_found" else 400
    return HTTPException(status, {"code": exc.code, "message": exc.message})


async def _step(call):
    """One HPID step. HPR's own reason for a refusal ("Aadhaar Number/Virtual
    ID is invalid", a wrong OTP) is the desk's to act on, so it is passed back;
    other failures are mapped as every HPR failure is."""
    try:
        return await call
    except AbdmRejected as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        messages = [str(d.get("message")) for d in detail.get("details") or [] if isinstance(d, dict) and d.get("message")]
        if any(hpid.TXN_MISSING in m for m in messages):
            # HPR's sandbox defect: its verify cannot find its own transaction.
            raise HTTPException(400, {"code": "hpid_inapp_unavailable", "message":
                "HPR could not verify this OTP in HealthDoc (NHA's in-app verification is not working). "
                "Verify on NHA's page instead."}) from None
        raise HTTPException(400, {"code": "hpr_refused", "message": "; ".join(messages)
                                  or f"HPR refused this (HTTP {exc.status_code})"}) from None
    except hpid.HpidError as exc:
        raise _refused(exc) from None
    except (AbdmNotConfigured, AbdmUnavailable, AbdmAuthError) as exc:
        await _hfr(_raise(exc))


class HpidSession(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)


class HpidAadhaar(BaseModel):
    #: Encrypted for HPR at once; never stored or logged.
    aadhaar: str = Field(pattern=r"^[2-9]\d{11}$", repr=False)
    consent_accepted: Literal[True]
    consent_version: Literal["nha-hpid-consent-2026-10-05"]
    captcha_id: str = Field(min_length=1, max_length=64)
    captcha_answer: str = Field(min_length=1, max_length=16)


class HpidMobile(HpidSession):
    mobile: str = Field(pattern=r"^[6-9]\d{9}$")


class HpidOtp(HpidSession):
    otp: str = Field(pattern=r"^\d{6}$")


class HpidCreate(HpidSession):
    #: The part before @hpr.abdm; HPR adds the domain.
    hpr_id: str = Field(min_length=4, max_length=48)
    email: str = Field(max_length=120, pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
    password: str = Field(min_length=8, max_length=64, repr=False)
    category_code: int = Field(ge=1, le=999)
    subcategory_code: int = Field(ge=1, le=999)
    #: HPR's lookup ids, as its lists return them; the server sends their ISO codes.
    state_id: str = Field(pattern=_ID)
    district_id: str = Field(pattern=_ID)
    role: Literal["PROFESSIONAL", "FACILITY_MANAGER", "BOTH"] = "PROFESSIONAL"


@router.get("/hpid/consent")
async def hpid_consent() -> dict:
    """HPR-003: NHA's consent text, shown before the Aadhaar number is taken."""
    return {"version": HPID_CONSENT_VERSION, "text": HPID_CONSENT_TEXT}


@router.get("/captcha")
async def hpid_captcha() -> dict:
    """HPR-006: a captcha before an Aadhaar OTP is sent."""
    captcha_id, png = await captcha.issue()
    return {"captcha_id": captcha_id, "image": "data:image/png;base64," + base64.b64encode(png).decode()}


@router.post("/hpid/aadhaar")
async def hpid_aadhaar(payload: HpidAadhaar, current_db_user: CurrentDbUser, db: DbSession) -> dict:
    """HPR-002 to 007: send the Aadhaar OTP, after the consent and captcha."""
    if not await captcha.check(payload.captcha_id, payload.captcha_answer):
        raise HTTPException(400, {"code": "captcha_invalid", "message": "The captcha did not match; try a new one"})
    try:
        session_id, hint = await _step(hpid.send_aadhaar_otp(
            facility_id=current_db_user.facility_id, user_id=current_db_user.id, aadhaar=payload.aadhaar))
    except hpid.HpidError as exc:
        raise _refused(exc) from None
    await write_audit_log(db, facility_id=current_db_user.facility_id, action=AuditAction.CREATE,
                          resource_type="hpid_consent", user_id=current_db_user.id,
                          new_value={"consent_version": payload.consent_version, "purpose": "HPID creation"})
    await db.commit()
    return {"session_id": session_id, "masked_mobile": hint}


@router.post("/hpid/aadhaar/resend")
async def hpid_aadhaar_resend(payload: HpidSession, current_db_user: CurrentDbUser) -> dict:
    """HPR-008."""
    try:
        hint = await _step(hpid.resend_aadhaar_otp(
            facility_id=current_db_user.facility_id, user_id=current_db_user.id, session_id=payload.session_id))
    except hpid.HpidError as exc:
        raise _refused(exc) from None
    return {"masked_mobile": hint}


@router.post("/hpid/aadhaar/verify")
async def hpid_aadhaar_verify(payload: HpidOtp, current_db_user: CurrentDbUser) -> dict:
    """The Aadhaar KYC, or, for an Aadhaar that already holds an HPID, that
    professional signed in to HPR with their KYC."""
    try:
        return await _step(hpid.verify_aadhaar_otp(
            facility_id=current_db_user.facility_id, user_id=current_db_user.id,
            session_id=payload.session_id, otp=payload.otp))
    except hpid.HpidError as exc:
        raise _refused(exc) from None


@router.post("/hpid/link")
async def hpid_link(current_db_user: CurrentDbUser) -> dict:
    """NHA's own Aadhaar page, when the in-app verify is unavailable."""
    session_id, url = await _step(hpid.start_link(facility_id=current_db_user.facility_id, user_id=current_db_user.id))
    return {"session_id": session_id, "url": url}


@router.post("/hpid/link/check")
async def hpid_link_check(payload: HpidSession, current_db_user: CurrentDbUser) -> dict:
    """{"authenticated": false} until the professional finishes on NHA's page;
    then the same answer as an in-app verify."""
    return await _step(hpid.check_link(
        facility_id=current_db_user.facility_id, user_id=current_db_user.id, session_id=payload.session_id))


@router.post("/hpid/mobile")
async def hpid_mobile(payload: HpidMobile, current_db_user: CurrentDbUser) -> dict:
    try:
        return await _step(hpid.verify_mobile(
            facility_id=current_db_user.facility_id, user_id=current_db_user.id,
            session_id=payload.session_id, mobile=payload.mobile))
    except hpid.HpidError as exc:
        raise _refused(exc) from None


@router.post("/hpid/mobile/verify")
async def hpid_mobile_verify(payload: HpidOtp, current_db_user: CurrentDbUser) -> dict:
    try:
        return await _step(hpid.confirm_mobile(
            facility_id=current_db_user.facility_id, user_id=current_db_user.id,
            session_id=payload.session_id, otp=payload.otp))
    except hpid.HpidError as exc:
        raise _refused(exc) from None


@router.post("/hpid/create")
async def hpid_create(payload: HpidCreate, current_db_user: CurrentDbUser) -> dict:
    """Creates the HPID and signs the professional in to HPR with it."""
    iso = await _resolve_iso(states={payload.state_id}, districts={payload.district_id: payload.state_id})
    try:
        session, number = await _step(hpid.create(
            facility_id=current_db_user.facility_id, user_id=current_db_user.id,
            session_id=payload.session_id, hpr_id=payload.hpr_id.strip().lower(), email=payload.email.strip(),
            password=payload.password, category_code=payload.category_code,
            subcategory_code=payload.subcategory_code, state_code=iso[f"state:{payload.state_id}"],
            district_code=iso[f"district:{payload.district_id}"], role=payload.role,
        ))
    except hpid.HpidError as exc:
        raise _refused(exc) from None
    return {"hpr_id": session.hpr_id, "hpr_id_number": number, "logged_in": True,
            "expires_at": session.expires_at}


# ----------------------------------------------------------------- HPR's ISO codes


async def _resolve_iso(
    *, states: set[str] = frozenset(), districts: dict[str, str] | None = None,
    sub_districts: dict[str, str] | None = None,
) -> dict[str, str]:
    """HPR's lists are looked up by id, but its payloads take each place's
    isoCode (the LGD code; NHA's register document). Resolved here from HPR's
    own masters, so the browser never supplies a code HPR stores."""
    iso: dict[str, str] = {}
    if states:
        rows = _list(await _hfr(client.call("GET", "/apis/v1/masters/states")))
        by_id = {str(row.get("id")): str(row.get("isoCode") or "") for row in rows}
        for state in states:
            if not by_id.get(state):
                raise HTTPException(422, {"code": "hpr_place_unknown", "message": "HPR does not list this state"})
            iso[f"state:{state}"] = by_id[state]
    for district, state in (districts or {}).items():
        rows = _list(await _hfr(client.call("GET", f"/apis/v1/masters/district/{state}")))
        code = next((str(r.get("isoCode") or "") for r in rows if str(r.get("id")) == district), "")
        if not code:
            raise HTTPException(422, {"code": "hpr_place_unknown", "message": "HPR does not list this district"})
        iso[f"district:{district}"] = code
    for sub, district in (sub_districts or {}).items():
        rows = _list(await _hfr(client.call("GET", f"/apis/v1/masters/sub-districts/{district}")))
        code = next((str(r.get("isoCode") or "") for r in rows if str(r.get("id")) == sub), "")
        if not code:
            raise HTTPException(422, {"code": "hpr_place_unknown", "message": "HPR does not list this sub-district"})
        iso[f"subdistrict:{sub}"] = code
    return iso


# ----------------------------------------------------------------- registration in HPR (HPR-018 to 079)


async def _signed_in(current_db_user) -> tuple[hpr_login.HprSession, str]:
    held = await hpr_login.current(current_db_user.facility_id, current_db_user.id)
    if held is None:
        raise HTTPException(409, {"code": "hpr_login_required", "message": "Sign in to HPR as the professional first"})
    return held


async def _kyc(current_db_user) -> dict:
    kyc = await hpr_login.kyc(current_db_user.facility_id, current_db_user.id)
    if not kyc:
        # A password or OTP login hands over only a token; HPR's KYC comes
        # with Aadhaar verification (HPID creation, or an existing HPID found).
        raise HTTPException(409, {"code": "hpr_kyc_required",
                                  "message": "Verify the professional's Aadhaar under “Create an HPID” to load their details"})
    return kyc


@router.get("/profile")
async def hpr_profile(current_db_user: CurrentDbUser) -> dict:
    """HPR-019 to 037: the signed-in professional's Aadhaar details, shown
    read-only on the registration form."""
    session, _ = await _signed_in(current_db_user)
    return hpid.public(await _kyc(current_db_user)) | {
        "hpr_id": session.hpr_id, "hpr_id_number": session.hpr_id_number}


@router.get("/professional")
async def hpr_professional(current_db_user: CurrentDbUser) -> dict:
    """HPR-078: what HPR holds for the signed-in professional (its public,
    masked view; NHA's Fetch Professional Details document)."""
    session, _ = await _signed_in(current_db_user)
    if not session.hpr_id_number:
        raise HTTPException(409, {"code": "hpr_login_required", "message": "This HPR login carries no HPR ID number"})
    body = await _hfr(client.call("POST", "/apis/v1/doctors/fetch-professional-info", json={"practitioner": {
        "id": session.hpr_id_number, "name": "", "contactNumber": "", "state": "", "registrationNumber": ""}}))
    rows = body.get("practitioners") if isinstance(body, dict) else None
    # HPR nests the list one level deeper than a flat list (5 Oct live; NHA's document agrees).
    while isinstance(rows, list) and rows and isinstance(rows[0], list):
        rows = rows[0]
    return {"practitioner": rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None}


async def _raise(exc: Exception):
    raise exc


async def _submit(path: str, payload: hpr_registration.Professional, current_db_user) -> dict:
    session, token = await _signed_in(current_db_user)
    kyc = await _kyc(current_db_user)
    comm = payload.communication_address
    quals = payload.registration.qualifications
    iso = await _resolve_iso(
        states={q.state for q in quals} | ({comm.state} if comm else set()),
        districts={comm.district: comm.state} if comm else None,
        sub_districts={comm.sub_district: comm.district} if comm and comm.sub_district else None,
    )
    try:
        practitioner = hpr_registration.practitioner(payload, kyc, iso)
    except hpr_registration.HprKycMissing as exc:
        raise HTTPException(409, {"code": "hpr_kyc_required", "message": str(exc)}) from None
    body = {"practitioner": practitioner, "hprToken": token}
    try:
        answer = await client.call("POST", path, json=body)
    except AbdmRejected as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        messages = [str(d.get("message")) for d in detail.get("details") or [] if isinstance(d, dict) and d.get("message")]
        raise HTTPException(400, {"code": "hpr_registration_refused",
                                  "messages": messages or [f"HPR refused this (HTTP {exc.status_code})"]}) from None
    except (AbdmNotConfigured, AbdmUnavailable, AbdmAuthError) as exc:
        # Mapped as every HPR failure is, without sending the registration again.
        await _hfr(_raise(exc))
    try:
        result = hpr_registration.outcome(answer)
    except ValueError as exc:
        raise HTTPException(400, {"code": "hpr_registration_refused",
                                  "messages": [hpr_registration.safe_text(str(exc))]}) from None
    return result | {"hpr_id_number": session.hpr_id_number}


@router.post("/professional")
async def register_professional(payload: hpr_registration.Professional, current_db_user: CurrentDbUser) -> dict:
    """HPR-018 to 077: register the signed-in professional in HPR."""
    return await _submit("/apis/v1/doctors/register-professional-new", payload, current_db_user)


@router.post("/professional/update")
async def update_professional(payload: hpr_registration.Professional, current_db_user: CurrentDbUser) -> dict:
    """HPR-079: the same form, sent as an update."""
    return await _submit("/apis/v1/doctors/update-professional-new", payload, current_db_user)


@router.get("/master/registration-options")
async def registration_options() -> dict:
    """NHA's fixed lists for registration (register document and Master Data
    workbook), which HPR serves no master call for."""
    pairs = lambda mapping: [{"code": str(code), "label": label} for code, label in mapping.items()]  # noqa: E731
    return {
        "salutations": pairs(hpr_registration.SALUTATIONS),
        "categories": [{"code": "1", "label": "Doctor"}, {"code": "2", "label": "Nurse"}, {"code": "6", "label": "Pharmacist"}],
        "doctor_systems": pairs(hpr_registration.DOCTOR_SYSTEMS),
        "nurse_types": pairs(hpr_registration.NURSE_TYPES),
        "pharmacist_type": {"code": str(hpr_registration.PHARMACIST_TYPE), "label": "Pharmacist"},
        "work_status": [{"code": "PRIVATE", "label": "Private only"}, {"code": "GOVERNMENT", "label": "Government only"},
                        {"code": "BOTH", "label": "Both"}],
        "government_types": [{"code": "CENTRAL", "label": "Central government"}, {"code": "STATE", "label": "State government"}],
        "purposes": list(hpr_registration.PURPOSES),
        "not_working_reasons": list(hpr_registration.NOT_WORKING_REASONS),
        "months": list(hpr_registration.MONTHS),
    }

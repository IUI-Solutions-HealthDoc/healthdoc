"""Healthcare Professionals Registry for the facility administrator (ABDM M4, HPR).

HPR's master data and HPID creation (HPR-002 to 011). Master lists come back
as {code, label}; HPR's own field names differ per list. HPR's state and
district ids are its own, not LGD codes (district/27 is Punjab, 5 Oct live),
so every HPR form takes them from these lists only.
"""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.deps import CurrentDbUser, require_roles
from app.integrations.abdm.hfr import client, hpid
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
    hpr_type: Literal["doctor", "nurse"] = "doctor",
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


# ----------------------------------------------------------------- HPID creation (HPR-002 to 011)


def _refused(exc: hpid.HpidError) -> HTTPException:
    status = 404 if exc.code == "hpid_session_not_found" else 400
    return HTTPException(status, {"code": exc.code, "message": exc.message})


class HpidSession(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)


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
    state_code: str = Field(pattern=_ID)
    district_code: str = Field(pattern=_ID)


@router.post("/hpid/start")
async def hpid_start(current_db_user: CurrentDbUser) -> dict:
    """Opens NHA's Aadhaar page; the professional authenticates there, so
    HealthDoc never sees their Aadhaar number or its OTP."""
    try:
        session_id, url = await _hfr(hpid.start(facility_id=current_db_user.facility_id, user_id=current_db_user.id))
    except hpid.HpidError as exc:
        raise _refused(exc) from None
    return {"session_id": session_id, "url": url}


@router.post("/hpid/check")
async def hpid_check(payload: HpidSession, current_db_user: CurrentDbUser) -> dict:
    try:
        return await _hfr(hpid.check(
            facility_id=current_db_user.facility_id, user_id=current_db_user.id, session_id=payload.session_id))
    except hpid.HpidError as exc:
        raise _refused(exc) from None


@router.post("/hpid/mobile")
async def hpid_mobile(payload: HpidMobile, current_db_user: CurrentDbUser) -> dict:
    try:
        return await _hfr(hpid.verify_mobile(
            facility_id=current_db_user.facility_id, user_id=current_db_user.id,
            session_id=payload.session_id, mobile=payload.mobile))
    except hpid.HpidError as exc:
        raise _refused(exc) from None


@router.post("/hpid/mobile/verify")
async def hpid_mobile_verify(payload: HpidOtp, current_db_user: CurrentDbUser) -> dict:
    try:
        return await _hfr(hpid.confirm_mobile(
            facility_id=current_db_user.facility_id, user_id=current_db_user.id,
            session_id=payload.session_id, otp=payload.otp))
    except hpid.HpidError as exc:
        raise _refused(exc) from None


@router.post("/hpid/create")
async def hpid_create(payload: HpidCreate, current_db_user: CurrentDbUser) -> dict:
    """Creates the HPID and signs the professional in to HPR with it."""
    try:
        session, number = await _hfr(hpid.create(
            facility_id=current_db_user.facility_id, user_id=current_db_user.id,
            session_id=payload.session_id, hpr_id=payload.hpr_id.strip().lower(), email=payload.email.strip(),
            password=payload.password, category_code=payload.category_code,
            subcategory_code=payload.subcategory_code, state_code=payload.state_code,
            district_code=payload.district_code,
        ))
    except hpid.HpidError as exc:
        raise _refused(exc) from None
    return {"hpr_id": session.hpr_id, "hpr_id_number": number, "logged_in": True,
            "expires_at": session.expires_at}

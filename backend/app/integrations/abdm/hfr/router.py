"""Health Facility Registry for the facility administrator (ABDM M4, HFR).

Covers the HFR workbook's search cases (HFR-001 to 009), the master data and
LGD lists every HFR form draws from, registration under the facility manager's
HPR login (HFR-010 to 063, submit HFR-116/117), editing a registered facility
(HFR-064 to 114) and bridge linkage (HFR-118 to 123). Field rules quoted below
are the workbook's.

HFR answers synchronously; a refusal is passed back as a 502 naming HFR, with
the status only, never HFR's body, which can echo what was sent.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.audit.service import write_audit_log
from app.auth.deps import CurrentDbUser, require_roles
from app.common.config import get_settings
from app.common.db import get_db
from app.integrations.abdm.client import (
    AbdmAuthError,
    AbdmNotConfigured,
    AbdmRejected,
    AbdmUnavailable,
)
from app.integrations.abdm.hfr import client, hpr_login, registration
from app.integrations.abdm.hfr.models import AbdmHfrRegistration
from app.integrations.abdm.hfr.registration import (
    AdditionalInformation,
    BasicInformation,
    DetailedInformation,
    HfrStepRefused,
    SubmitFacility,
)

log = logging.getLogger("healthdoc.abdm")
router = APIRouter(
    prefix="/abdm/hfr",
    tags=["abdm"],
    dependencies=[Depends(require_roles("admin"))],
)

#: HFR-001: "12 digit alphanumeric value", "should start with IN".
FACILITY_ID = r"^IN[0-9A-Z]{10}$"
_CODE = r"^[0-9A-Za-z-]{1,20}$"
_LGD = r"^\d{1,6}$"
#: HFR-009: results per page default 10, not set by the user.
RESULTS_PER_PAGE = 10


async def _hfr(call):
    """Run one HFR call, mapping failures without echoing HFR's body."""
    try:
        return await call
    except AbdmNotConfigured:
        raise HTTPException(503, {"code": "abdm_unavailable", "message": "ABDM credentials are not configured"}) from None
    except AbdmUnavailable:
        raise HTTPException(503, {"code": "abdm_unavailable", "message": "HFR did not respond"}) from None
    except AbdmAuthError:
        raise HTTPException(
            502, {"code": "hfr_not_permitted", "message": "HFR refused this client. NHA assigns the HFR role."}
        ) from None
    except AbdmRejected as exc:
        log.warning("HFR declined a request (%s)", exc.status_code)
        raise HTTPException(
            502, {"code": "hfr_rejected", "message": f"HFR refused the request (HTTP {exc.status_code})"}
        ) from exc


def _rows(body, key: str = "data") -> list[dict]:
    """HFR lists come bare or under `data`; anything else is a broken answer."""
    rows = body.get(key) if isinstance(body, dict) else body
    if not isinstance(rows, list):
        raise HTTPException(502, {"code": "hfr_bad_response", "message": "HFR returned an unexpected list"})
    return rows


# ----------------------------------------------------------------- master data


@router.get("/master-types")
async def master_types() -> dict:
    return {"types": _rows(await _hfr(client.master_types()), "masterTypes")}


@router.get("/master/{kind}")
async def master_data(kind: str) -> dict:
    # The type travels in HFR's query string; only the shape of a master type
    # (OWNER, FAC-STATUS, CENTRAL-GOVERNMENT...) is passed on.
    if not re.fullmatch(r"[A-Z][A-Z-]{1,40}", kind):
        raise HTTPException(422, {"code": "hfr_master_type_invalid", "message": "Unknown master type"})
    return {"type": kind, "data": _rows(await _hfr(client.master_data(kind)))}


@router.get("/lgd/states")
async def lgd_states() -> dict:
    states = _rows(await _hfr(client.lgd_states()), "states")
    return {"states": [{"code": s.get("code"), "name": s.get("name")} for s in states]}


@router.get("/lgd/districts")
async def lgd_districts(state_code: Annotated[str, Query(pattern=_LGD)]) -> dict:
    return {"districts": _rows(await _hfr(client.lgd_districts(state_code)), "districts")}


@router.get("/lgd/subdistricts")
async def lgd_subdistricts(district_code: Annotated[str, Query(pattern=_LGD)]) -> dict:
    return {"subdistricts": _rows(await _hfr(client.lgd_subdistricts(district_code)), "subdistricts")}


@router.get("/facility-types")
async def facility_types(
    ownership_code: Annotated[str, Query(pattern=_CODE)],
    system_of_medicine_code: Annotated[str, Query(pattern=_CODE)],
) -> dict:
    return {"data": _rows(await _hfr(client.facility_types(ownership_code, system_of_medicine_code)))}


@router.get("/facility-subtypes")
async def facility_subtypes(facility_type_code: Annotated[str, Query(pattern=_CODE)]) -> dict:
    return {"data": _rows(await _hfr(client.facility_subtypes(facility_type_code)))}


@router.get("/owner-subtypes")
async def owner_subtypes(
    ownership_code: Annotated[str, Query(pattern=_CODE)],
    owner_subtype_code: Annotated[str | None, Query(pattern=_CODE)] = None,
) -> dict:
    return {"data": _rows(await _hfr(client.owner_subtypes(ownership_code, owner_subtype_code)))}


@router.get("/specialities")
async def specialities(system_of_medicine_code: Annotated[str, Query(pattern=_CODE)]) -> dict:
    return {"data": _rows(await _hfr(client.specialities(system_of_medicine_code)))}


# ----------------------------------------------------------------- search


class FacilitySearch(BaseModel):
    """HFR-001 to 009. A facility id alone is enough; otherwise the name,
    ownership and state are required, and district, sub-district and pincode
    narrow the search."""

    facility_id: str | None = Field(default=None, pattern=FACILITY_ID)
    facility_name: str | None = Field(default=None, min_length=1, max_length=200)
    ownership_code: str | None = Field(default=None, pattern=_CODE)
    state_lgd_code: str | None = Field(default=None, pattern=_LGD)
    district_lgd_code: str | None = Field(default=None, pattern=_LGD)
    subdistrict_lgd_code: str | None = Field(default=None, pattern=_LGD)
    #: HFR-007: at most six digits.
    pincode: str | None = Field(default=None, pattern=r"^\d{1,6}$")
    #: HFR-008: defaults to 1 and is set by paging, not typed.
    page: int = Field(default=1, ge=1, le=1000)

    @field_validator("facility_name")
    @classmethod
    def _alphanumeric(cls, value: str | None) -> str | None:
        # HFR-002: alphanumeric, full or partial name.
        if value is not None and not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z .&()'/-]*", value.strip()):
            raise ValueError("Facility name must be alphanumeric")
        return value.strip() if value else value

    @model_validator(mode="after")
    def _enough_to_search(self) -> FacilitySearch:
        if self.facility_id:
            return self
        missing = [
            label
            for label, value in (
                ("facility name", self.facility_name),
                ("ownership", self.ownership_code),
                ("state", self.state_lgd_code),
            )
            if not value
        ]
        if missing:
            raise ValueError("Without a facility id, give the " + ", ".join(missing))
        return self


@router.post("/facilities/search")
async def search_facilities(payload: FacilitySearch) -> dict:
    criteria = {
        "facilityId": payload.facility_id or "",
        "facilityName": "" if payload.facility_id else payload.facility_name or "",
        "ownershipCode": "" if payload.facility_id else payload.ownership_code or "",
        "stateLGDCode": "" if payload.facility_id else payload.state_lgd_code or "",
        "districtLGDCode": "" if payload.facility_id else payload.district_lgd_code or "",
        "subDistrictLGDCode": "" if payload.facility_id else payload.subdistrict_lgd_code or "",
        "pincode": "" if payload.facility_id else payload.pincode or "",
        "page": str(payload.page),
        "resultsPerPage": str(RESULTS_PER_PAGE),
    }
    body = await _hfr(client.search_facilities(criteria))
    facilities = _rows(body, "facilities")
    counts = body if isinstance(body, dict) else {}
    total, pages = counts.get("totalFacilities"), counts.get("numberOfPages")
    return {
        "facilities": facilities,
        "page": payload.page,
        "results_per_page": RESULTS_PER_PAGE,
        "total": total if isinstance(total, int) else None,
        "pages": pages if isinstance(pages, int) else None,
    }


# ----------------------------------------------------------------- bridge linkage


class BridgeService(BaseModel):
    #: HFR-122: HIP, HIU and so on; HIECM validates.
    type: Literal["HIP", "HIU"]
    #: HFR-121: the name patients see when searching in a PHR app; the
    #: hospital name, with a suffix to tell two services apart.
    hip_name: str = Field(min_length=1, max_length=200)
    #: HFR-123: boolean.
    active: bool = True


class BridgeLink(BaseModel):
    """HFR-118 to 123: link this facility's HFR id to HealthDoc's bridge."""

    facility_id: str = Field(pattern=FACILITY_ID)
    services: list[BridgeService] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def _one_per_type(self) -> BridgeLink:
        if len({service.type for service in self.services}) != len(self.services):
            raise ValueError("Give each service type once")
        return self


@router.post("/bridge-link")
async def link_bridge(payload: BridgeLink) -> dict:
    """The facility name is fetched from HFR by id (HFR-119), not typed; the
    bridge id is this deployment's own (HFR-120)."""
    bridge_id = get_settings().abdm_client_id
    if not bridge_id or bridge_id == "change-me":
        raise HTTPException(503, {"code": "abdm_unavailable", "message": "ABDM bridge id is not configured"})
    found = _rows(
        await _hfr(client.search_facilities({
            "facilityId": payload.facility_id, "facilityName": "", "ownershipCode": "",
            "stateLGDCode": "", "districtLGDCode": "", "subDistrictLGDCode": "", "pincode": "",
            "page": "1", "resultsPerPage": str(RESULTS_PER_PAGE),
        })),
        "facilities",
    )
    match = next((row for row in found if row.get("facilityId") == payload.facility_id), None)
    if match is None or not isinstance(match.get("facilityName"), str) or not match["facilityName"].strip():
        # HFR-118: the id must exist in HFR.
        raise HTTPException(404, {"code": "hfr_facility_not_found", "message": "No HFR facility has this id"})
    services = [
        {"bridgeId": bridge_id, "hipName": service.hip_name.strip(), "type": service.type, "active": service.active}
        for service in payload.services
    ]
    await _hfr(client.link_bridge(payload.facility_id, match["facilityName"].strip(), services))
    return {
        "facility_id": payload.facility_id,
        "facility_name": match["facilityName"].strip(),
        "bridge_id": bridge_id,
        "services": services,
    }


# ----------------------------------------------------------------- facility manager's HPR login


class HprOtpStart(BaseModel):
    hpr_id: str = Field(min_length=3, max_length=60)
    method: Literal["AADHAAR_OTP"] = "AADHAAR_OTP"


class HprOtpConfirm(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    otp: str = Field(pattern=r"^\d{6}$")


class HprPassword(BaseModel):
    hpr_id: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=1, max_length=128, repr=False)


def _hpr_session_out(session: hpr_login.HprSession | None) -> dict:
    if session is None:
        return {"logged_in": False}
    return {
        "logged_in": True,
        "hpr_id": session.hpr_id,
        "hpr_id_number": session.hpr_id_number,
        "expires_at": session.expires_at,
    }


def _hpr_refused(exc: hpr_login.HprLoginError) -> HTTPException:
    status = 404 if exc.code == "hpr_login_session_not_found" else 400
    return HTTPException(status, {"code": exc.code, "message": exc.message})


@router.get("/hpr-login")
async def hpr_login_state(current_db_user: CurrentDbUser) -> dict:
    held = await hpr_login.current(current_db_user.facility_id, current_db_user.id)
    return _hpr_session_out(held[0] if held else None)


@router.post("/hpr-login/otp")
async def hpr_login_otp(payload: HprOtpStart, current_db_user: CurrentDbUser) -> dict:
    """Send an OTP for the facility manager's HPR login. Typed by them on this screen."""
    try:
        session_id, hint = await _hfr(hpr_login.start_otp(
            facility_id=current_db_user.facility_id, user_id=current_db_user.id,
            hpr_id=payload.hpr_id.strip(), method=payload.method,
        ))
    except hpr_login.HprLoginError as exc:
        raise _hpr_refused(exc) from None
    return {"session_id": session_id, "masked_mobile": hint}


@router.post("/hpr-login/verify")
async def hpr_login_verify(payload: HprOtpConfirm, current_db_user: CurrentDbUser) -> dict:
    try:
        session = await _hfr(hpr_login.confirm_otp(
            facility_id=current_db_user.facility_id, user_id=current_db_user.id,
            session_id=payload.session_id, otp=payload.otp,
        ))
    except hpr_login.HprLoginError as exc:
        raise _hpr_refused(exc) from None
    return _hpr_session_out(session)


@router.post("/hpr-login/password")
async def hpr_login_password(payload: HprPassword, current_db_user: CurrentDbUser) -> dict:
    """The password goes to HPR and nowhere else: not stored, logged or echoed."""
    try:
        session = await _hfr(hpr_login.password_login(
            facility_id=current_db_user.facility_id, user_id=current_db_user.id,
            hpr_id=payload.hpr_id.strip(), password=payload.password,
        ))
    except hpr_login.HprLoginError as exc:
        raise _hpr_refused(exc) from None
    return _hpr_session_out(session)


@router.delete("/hpr-login")
async def hpr_logout(current_db_user: CurrentDbUser) -> dict:
    await hpr_login.logout(current_db_user.facility_id, current_db_user.id)
    return {"logged_in": False}


# ---------------------------------------------------------------- registration

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _manager(current_db_user) -> hpr_login.HprSession:
    """The signed-in facility manager; registration happens under their HPR ID."""
    held = await hpr_login.current(current_db_user.facility_id, current_db_user.id)
    if held is None or not held[0].hpr_id_number:
        raise HTTPException(
            409, {"code": "hpr_login_required", "message": "Sign in to HPR as the facility manager first"}
        )
    return held[0]


async def _step(call) -> object:
    """Run one registration call. HFR's own field messages are about the
    facility the admin typed, so a refusal passes them back to be corrected."""
    try:
        return await call
    except AbdmRejected as exc:
        log.warning("HFR declined a registration step (%s)", exc.status_code)
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        messages = registration._messages(detail) or [f"HFR refused this step (HTTP {exc.status_code})"]
        raise HTTPException(400, {"code": "hfr_registration_refused", "messages": messages}) from exc
    except (AbdmNotConfigured, AbdmUnavailable, AbdmAuthError):
        return await _hfr(call)


def _refused(exc: HfrStepRefused) -> HTTPException:
    return HTTPException(400, {"code": "hfr_registration_refused", "messages": exc.messages})


async def _remember(db, current_db_user, tracking_id: str, **fields) -> AbdmHfrRegistration:
    """Keep what HFR accepted under this tracking id; an edit opens with it."""
    row = (await db.execute(select(AbdmHfrRegistration).where(
        AbdmHfrRegistration.facility_id == current_db_user.facility_id,
        AbdmHfrRegistration.tracking_id == tracking_id,
    ))).scalar_one_or_none()
    if row is None:
        # The id is set here, as for the other ABDM rows, so the row is
        # addressable before the database has answered.
        row = AbdmHfrRegistration(
            id=uuid.uuid4(), facility_id=current_db_user.facility_id, tracking_id=tracking_id,
            created_by=current_db_user.id)
        db.add(row)
    else:
        row.updated_by = current_db_user.id
    for field, value in fields.items():
        setattr(row, field, value)
    return row


def _saved_basic(form: BasicInformation) -> dict:
    # The images go to HFR only (registration.Upload); an edit attaches them again.
    return form.model_dump(mode="json", exclude={"tracking_id", "board_photo", "building_photo", "address_proofs"})


async def _audit(db, current_db_user, step: str, values: dict) -> None:
    await write_audit_log(
        db,
        facility_id=current_db_user.facility_id,
        action=AuditAction.CREATE if step == "submit" else AuditAction.UPDATE,
        resource_type="hfr_registration",
        user_id=current_db_user.id,
        new_value={"step": step, **values},
    )


@router.post("/registration/basic")
async def register_basic(
    payload: BasicInformation, current_db_user: CurrentDbUser, db: DbSession
) -> dict:
    """HFR-010 to 038. Returns the tracking id the later steps continue.

    With the tracking id of a registered facility this is its edit
    (HFR-064 to 092): HFR's basic-details update is the same call.
    """
    manager = await _manager(current_db_user)
    body = await _step(client.save_basic_information(
        registration.basic_payload(payload), manager.hpr_id_number))
    try:
        tracking, status, message = registration.tracking_from(body)
    except HfrStepRefused as exc:
        raise _refused(exc) from None
    await _remember(db, current_db_user, tracking, basic=_saved_basic(payload), status=status)
    await _audit(db, current_db_user, "basic", {
        "tracking_id": tracking, "facility_name": payload.name, "hpr_id": manager.hpr_id,
        **({"edit": True} if payload.tracking_id else {})})
    await db.commit()
    return {"tracking_id": tracking, "status": status, "message": message}


@router.post("/registration/additional")
async def register_additional(
    payload: AdditionalInformation, current_db_user: CurrentDbUser, db: DbSession
) -> dict:
    await _manager(current_db_user)
    body = await _step(client.save_additional_information(registration.additional_payload(payload)))
    try:
        tracking, status, message = registration.tracking_from(body)
    except HfrStepRefused as exc:
        raise _refused(exc) from None
    await _remember(db, current_db_user, tracking,
                    additional=payload.model_dump(mode="json", exclude={"tracking_id"}), status=status)
    await _audit(db, current_db_user, "additional", {"tracking_id": tracking})
    await db.commit()
    return {"tracking_id": tracking, "status": status, "message": message}


@router.post("/registration/detailed")
async def register_detailed(
    payload: DetailedInformation, current_db_user: CurrentDbUser, db: DbSession
) -> dict:
    await _manager(current_db_user)
    body = await _step(client.save_detailed_information(registration.detailed_payload(payload)))
    try:
        tracking, status, message = registration.tracking_from(body)
    except HfrStepRefused as exc:
        raise _refused(exc) from None
    await _remember(db, current_db_user, tracking,
                    detailed=payload.model_dump(mode="json", exclude={"tracking_id"}), status=status)
    await _audit(db, current_db_user, "detailed", {"tracking_id": tracking})
    await db.commit()
    return {"tracking_id": tracking, "status": status, "message": message}


@router.post("/registration/submit")
async def register_submit(
    payload: SubmitFacility, current_db_user: CurrentDbUser, db: DbSession
) -> dict:
    """HFR-116/117: submit the saved details; HFR returns the facility id.
    After an edit this is the resubmit, under the same tracking id."""
    manager = await _manager(current_db_user)
    body = await _step(client.submit_facility(registration.submit_payload(payload), manager.hpr_id_number))
    try:
        facility_id, status, message = registration.facility_from(body)
    except HfrStepRefused as exc:
        raise _refused(exc) from None
    await _remember(db, current_db_user, payload.tracking_id, hfr_facility_id=facility_id,
                    status=status, submitted_at=datetime.now(UTC))
    await _audit(db, current_db_user, "submit", {
        "tracking_id": payload.tracking_id, "hfr_facility_id": facility_id, "hpr_id": manager.hpr_id})
    await db.commit()
    return {"facility_id": facility_id, "status": status, "message": message}


# ---------------------------------------------------------------- editing a registered facility


def _registration_out(row: AbdmHfrRegistration, *, forms: bool) -> dict:
    out = {
        "tracking_id": row.tracking_id,
        "facility_id": row.hfr_facility_id,
        "facility_name": (row.basic or {}).get("name"),
        "status": row.status,
        "submitted_at": row.submitted_at,
        "updated_at": row.updated_at,
    }
    if forms:
        out.update(basic=row.basic, additional=row.additional, detailed=row.detailed)
    return out


@router.get("/registrations")
async def list_registrations(current_db_user: CurrentDbUser, db: DbSession) -> dict:
    """The facilities this HealthDoc facility registered in HFR, newest first."""
    rows = (await db.execute(
        select(AbdmHfrRegistration)
        .where(AbdmHfrRegistration.facility_id == current_db_user.facility_id)
        .order_by(AbdmHfrRegistration.updated_at.desc())
        .limit(50)
    )).scalars().all()
    return {"registrations": [_registration_out(row, forms=False) for row in rows]}


@router.get("/registrations/{tracking_id}")
async def get_registration(
    tracking_id: Annotated[str, Path(pattern=r"^\d{1,20}$")], current_db_user: CurrentDbUser, db: DbSession
) -> dict:
    """The forms HFR accepted for this tracking id, to open its edit
    (HFR-064 to 114). Images are not kept and are attached again."""
    row = (await db.execute(select(AbdmHfrRegistration).where(
        AbdmHfrRegistration.facility_id == current_db_user.facility_id,
        AbdmHfrRegistration.tracking_id == tracking_id,
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, {"code": "hfr_registration_not_found",
                                  "message": "HealthDoc has no HFR registration with this tracking id"})
    return _registration_out(row, forms=True)

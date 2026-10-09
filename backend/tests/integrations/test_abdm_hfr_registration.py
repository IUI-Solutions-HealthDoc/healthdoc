"""HFR facility registration under the manager's HPR login (M4 HFR-010 to 117).

Shapes from NHA's M4 Postman (v1.5 onboarding): basic-information and
submit-facility carry x-hprid-auth with the HPR ID number; additional and
detailed information continue the tracking id. Field rules are the workbook's.
"""

import base64
import json
import time
import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.common.db import get_db
from app.integrations.abdm.client import AbdmRejected
from app.integrations.abdm.hfr import client, hpr_login, registration
from app.integrations.abdm.hfr import models as hfr_models
from app.integrations.abdm.hfr import router as hfr_router
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio
HPR_NUMBER = "71-1401-4301-6184"
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"synthetic board" * 4).decode()


def _jwt(**claims) -> str:
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{part({'alg': 'RS512'})}.{part(claims)}.signature"


class _Redis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


class _Hfr:
    def __init__(self):
        self.calls = []
        self.answers = {}

    async def call(self, method, path, *, json=None, headers=None):
        self.calls.append((path, json, headers))
        answer = self.answers.get(path)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest_asyncio.fixture
async def desk(db, monkeypatch):
    facility = Facility(id=uuid.uuid4(), code=f"HR{uuid.uuid4().hex[:4]}", name="HFR desk", state_code="MH")
    admin = User(id=uuid.uuid4(), keycloak_sub=f"sub-{uuid.uuid4()}", username=f"adm{uuid.uuid4().hex[:6]}",
                 full_name="Facility Admin", facility_id=facility.id, is_active=True)
    db.add_all([facility, admin])
    await db.flush()
    redis, fake = _Redis(), _Hfr()
    monkeypatch.setattr(hpr_login, "get_redis", lambda: redis)
    monkeypatch.setattr(client, "call", fake.call)
    app = FastAPI()
    app.include_router(hfr_router.router)
    caller = DbUser(id=admin.id, keycloak_sub=admin.keycloak_sub, username=admin.username,
                    facility_id=facility.id, roles=["admin"])
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub=caller.keycloak_sub, roles=["admin"])
    app.dependency_overrides[get_current_db_user] = lambda: caller

    async def session():
        yield db

    app.dependency_overrides[get_db] = session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as http:
        yield {"fake": fake, "http": http, "facility": facility.id, "admin": admin.id, "db": db}


async def _sign_in(desk):
    token = _jwt(hprId="kumar682000@hpr.abdm", hprIdNumber=HPR_NUMBER, exp=int(time.time()) + 900)
    await hpr_login._keep(desk["facility"], desk["admin"], "kumar682000@hpr.abdm", token)


def _basic(**change):
    body = {
        "name": "HealthDoc Sandbox Test Hospital",
        "address": {
            "state_code": "27", "district_code": "490", "sub_district_code": "4194", "region": "U",
            "address_line1": "Synthetic Test Block, 1 Test Road", "address_line2": "Pune",
            "pincode": "411001", "latitude": "18.520430", "longitude": "73.856743",
        },
        "contact": {"email": "hfr-test@example.org", "mobile": "9000000001", "website": "example.org"},
        "ownership_code": "P", "ownership_subtype_code": "P", "ownership_subtype_code2": "PP02",
        "systems_of_medicine": ["M"], "types_of_service": ["OPD", "IPD"],
        "facility_type_code": "40", "facility_subtype_code": "28", "speciality_type": "MULTI",
        "operational_status": "F",
        "timings": [{"days": ["Mon", "Tue"], "hours": "9:00 AM - 6:00 PM"}, {"days": ["Sat"], "hours": "24*7"}],
        "board_photo": {"name": "board.png", "content": f"data:image/png;base64,{PNG}"},
        "building_photo": {"name": "building.png", "content": PNG},
    }
    body.update(change)
    return body


async def test_every_step_needs_the_manager_signed_in_to_hpr(desk):
    for path, body in (("basic", _basic()), ("additional", {"tracking_id": "1"}),
                       ("detailed", {"tracking_id": "1"}), ("submit", {"tracking_id": "1"})):
        response = await desk["http"].post(f"/abdm/hfr/registration/{path}", json=body)
        assert response.status_code == 409, (path, response.text)
        assert response.json()["detail"]["code"] == "hpr_login_required"
    assert desk["fake"].calls == []


async def test_basic_information_goes_under_the_managers_hpr_id_number(desk):
    await _sign_in(desk)
    desk["fake"].answers["/v1.5/facility/basic-information"] = {
        "trackingId": "76803", "status": "success", "message": "Facility is saved successfully", "errorStatus": None}
    response = await desk["http"].post("/abdm/hfr/registration/basic", json=_basic())
    assert response.status_code == 200, response.text
    assert response.json() == {"tracking_id": "76803", "status": "success", "message": "Facility is saved successfully"}
    path, body, headers = desk["fake"].calls[0]
    assert path == "/v1.5/facility/basic-information"
    assert headers == {"x-hprid-auth": HPR_NUMBER}
    info = body["facilityInformation"]
    assert body["trackingId"] == ""
    assert info["facilityAddressDetails"]["country"] == "India"
    assert info["facilityAddressDetails"]["subDistrictLGDCode"] == "4194"
    assert info["systemOfMedicineCode"] == "M" and info["typeOfServiceCode"] == "OPD,IPD"
    assert info["timingsOfFacility"] == [
        {"workingDays": "Mon", "openingHours": "9:00 AM - 6:00 PM"},
        {"workingDays": "Tue", "openingHours": "9:00 AM - 6:00 PM"},
        {"workingDays": "Sat", "openingHours": "24*7"},
    ]
    assert info["facilityUploads"]["facilityBoardPhoto"] == {"name": "board.png", "value": PNG}
    assert info["facilityUploads"]["facilityBuildingPhoto"] == {"name": "building.png", "value": PNG}
    assert info["abdmCompliantSoftware"] == [{"existingSoftwares": [], "anyOther": "HealthDoc"}]
    row = (await desk["db"].execute(select(AuditLog).where(AuditLog.resource_type == "hfr_registration"))).scalar_one()
    assert row.new_value == {"step": "basic", "tracking_id": "76803",
                             "facility_name": "HealthDoc Sandbox Test Hospital", "hpr_id": "kumar682000@hpr.abdm"}


@pytest.mark.parametrize(
    "change",
    [
        {"name": "1st Hospital"},
        {"name": "Hospital & Co"},
        {"address": {**_basic()["address"], "address_line1": "Block #4"}},
        {"address": {**_basic()["address"], "latitude": "91.000000"}},
        {"address": {**_basic()["address"], "longitude": "73.8567431"}},
        {"address": {**_basic()["address"], "pincode": "41100"}},
        {"contact": {"email": "not-an-email", "mobile": "9000000001"}},
        {"contact": {"email": "a@b.org", "mobile": "900000000"}},
        {"contact": {"email": "a@b.org", "mobile": "9000000001", "landline": "12345"}},
        {"timings": [{"days": ["Mon"], "hours": "9 to 5"}]},
        {"timings": [{"days": ["Mon"], "hours": "24*7"}, {"days": ["Mon"], "hours": "9:00 AM - 1:00 PM"}]},
        {"ownership_subtype_code": ""},
        {"ownership_subtype_code": "S"},
        {"ownership_code": "G", "ownership_subtype_code": "P"},
        {"ownership_subtype_code2": ""},
        {"board_photo": {"name": "board.pdf", "content": base64.b64encode(b"%PDF-1.7 not an image").decode()}},
        {"systems_of_medicine": []},
        {"building_photo": None},
    ],
)
async def test_fields_outside_the_workbook_rules_never_reach_hfr(desk, change):
    await _sign_in(desk)
    response = await desk["http"].post("/abdm/hfr/registration/basic", json=_basic(**change))
    assert response.status_code == 422, response.text
    assert desk["fake"].calls == []


async def test_hfrs_field_messages_come_back_to_be_corrected(desk):
    await _sign_in(desk)
    desk["fake"].answers["/v1.5/facility/basic-information"] = AbdmRejected(
        400, {"errorStatus": [{"field": "facilityContactNumber", "message": "Invalid mobile number"}]}, "rid")
    refused = await desk["http"].post("/abdm/hfr/registration/basic", json=_basic())
    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "code": "hfr_registration_refused", "messages": ["facilityContactNumber: Invalid mobile number"]}
    desk["fake"].answers["/v1.5/facility/basic-information"] = {
        "trackingId": None, "status": "failure", "errorStatus": [{"message": "Duplicate facility"}]}
    refused = await desk["http"].post("/abdm/hfr/registration/basic", json=_basic())
    assert refused.json()["detail"]["messages"] == ["Duplicate facility"]


async def test_the_later_steps_continue_the_tracking_id_and_derive_the_totals(desk):
    await _sign_in(desk)
    saved = {"trackingId": "76803", "status": "Saved", "message": "saved", "errorStatus": None}
    desk["fake"].answers["/v1.5/facility/additional-information"] = saved
    desk["fake"].answers["/v1.5/facility/detailed-information"] = saved
    additional = await desk["http"].post("/abdm/hfr/registration/additional", json={
        "tracking_id": "76803", "nin": "1234",
        "general": {"pharmacy": "YALL", "diagnostic_lab": "YIN", "imaging": "YALL"},
        "imaging_services": [{"service": "S136", "count": 2}],
    })
    assert additional.status_code == 200, additional.text
    _, body, headers = desk["fake"].calls[-1]
    assert headers is None
    assert body["linkedProgramIds"]["nin"] == "1234"
    assert body["generalInformation"] == {
        "hasDialysisCenter": "N", "hasPharmacy": "YALL", "hasBloodBank": "N", "hasCathLab": "N",
        "hasDiagnosticLab": "YIN", "hasImagingCenter": "YALL",
        "servicesByImagingCenter": [{"service": "S136", "count": 2}],
    }
    detailed = await desk["http"].post("/abdm/hfr/registration/detailed", json={
        "tracking_id": "76803",
        "specialities": [{"system_of_medicine": "M", "available": "Y", "codes": ["M-S1", "M-S2"]}],
        "infrastructure": {"ipd_beds_without_oxygen": 10, "ipd_beds_with_oxygen": 5,
                           "icu_beds_with_ventilators": 2, "hdu_beds_with_ventilators": 1},
        "diagnostic_services": ["S212"],
    })
    assert detailed.status_code == 200, detailed.text
    _, body, _ = desk["fake"].calls[-1]
    infra = body["medicalInfrastructure"]
    assert infra["totalNumberOfVentilators"] == 3
    assert infra["totalNumberOfBeds"] == 16, "IPD and HDU beds, not ICU, as HFR checks"
    assert body["specialities"] == [
        {"systemOfMedicineCode": "M", "isSpecializationAvalaible": "Y", "specialities": ["S1", "S2"]}]
    assert body["diagnosticServices"] == ["S212"]
    assert "pharmacyDetails" not in body and "imagingServices" not in body


@pytest.mark.parametrize(
    "change",
    [
        {"specialities": [{"system_of_medicine": "M", "available": "N", "codes": ["M-S1"]}]},
        {"infrastructure": {"ipd_beds_with_oxygen": 100}},
        {"tracking_id": "abc"},
    ],
)
async def test_detailed_information_keeps_the_workbook_limits(desk, change):
    await _sign_in(desk)
    response = await desk["http"].post("/abdm/hfr/registration/detailed", json={"tracking_id": "1", **change})
    assert response.status_code == 422, response.text
    assert desk["fake"].calls == []


async def test_submit_returns_the_new_facility_id_and_sends_no_source_the_operator_typed(desk):
    await _sign_in(desk)
    desk["fake"].answers["/v1.5/facility/submit-facility"] = {
        "facilityId": "IN0610090166", "status": "Created", "message": "Facility created successfully."}
    response = await desk["http"].post("/abdm/hfr/registration/submit", json={
        "tracking_id": "76803", "sourceOfInformation": "HRP_SUB_1"})
    assert response.status_code == 200, response.text
    assert response.json()["facility_id"] == "IN0610090166"
    path, body, headers = desk["fake"].calls[-1]
    assert (path, body, headers) == (
        "/v1.5/facility/submit-facility", {"trackingId": "76803"}, {"x-hprid-auth": HPR_NUMBER})
    row = (await desk["db"].execute(select(AuditLog).where(AuditLog.resource_type == "hfr_registration"))).scalar_one()
    assert row.new_value["hfr_facility_id"] == "IN0610090166"


async def test_a_submit_without_a_facility_id_is_not_success(desk):
    await _sign_in(desk)
    desk["fake"].answers["/v1.5/facility/submit-facility"] = {"status": "Failed", "message": "Tracking id not found"}
    response = await desk["http"].post("/abdm/hfr/registration/submit", json={"tracking_id": "76803"})
    assert response.status_code == 400
    assert response.json()["detail"]["messages"] == ["Tracking id not found"]


def test_a_state_government_facility_has_no_ownership_subtype():
    form = registration.BasicInformation.model_validate(
        _basic(ownership_code="G", ownership_subtype_code="", ownership_subtype_code2=""))
    info = registration.basic_payload(form)["facilityInformation"]
    assert (info["ownershipCode"], info["ownershipSubTypeCode"], info["ownershipSubTypeCode2"]) == ("G", "", "")


def test_the_payload_builders_never_invent_codes():
    form = registration.BasicInformation.model_validate(_basic(ownership_code="G", ownership_subtype_code="C",
                                                                ownership_subtype_code2="MOHF"))
    info = registration.basic_payload(form)["facilityInformation"]
    assert (info["ownershipCode"], info["ownershipSubTypeCode"], info["ownershipSubTypeCode2"]) == ("G", "C", "MOHF")


# ------------------------------------------------------------ editing (HFR-064 to 114)


async def _register(desk, tracking="76803"):
    saved = {"trackingId": tracking, "status": "Draft", "message": "saved", "errorStatus": None}
    for path in ("basic-information", "additional-information", "detailed-information"):
        desk["fake"].answers[f"/v1.5/facility/{path}"] = saved
    desk["fake"].answers["/v1.5/facility/submit-facility"] = {
        "facilityId": "IN0610090166", "status": "Submitted", "message": "Facility created successfully."}
    http = desk["http"]
    assert (await http.post("/abdm/hfr/registration/basic", json=_basic())).status_code == 200
    assert (await http.post("/abdm/hfr/registration/additional", json={
        "tracking_id": tracking, "nin": "1234", "general": {"pharmacy": "YALL"}})).status_code == 200
    assert (await http.post("/abdm/hfr/registration/detailed", json={
        "tracking_id": tracking, "infrastructure": {"ipd_beds_with_oxygen": 5}})).status_code == 200
    assert (await http.post("/abdm/hfr/registration/submit", json={"tracking_id": tracking})).status_code == 200


async def test_a_registered_facility_opens_for_edit_with_what_hfr_accepted(desk):
    await _sign_in(desk)
    await _register(desk)
    listed = (await desk["http"].get("/abdm/hfr/registrations")).json()["registrations"]
    assert [(r["tracking_id"], r["facility_id"], r["facility_name"], r["status"]) for r in listed] == [
        ("76803", "IN0610090166", "HealthDoc Sandbox Test Hospital", "Submitted")]
    assert "basic" not in listed[0], "the list carries no forms"
    saved = (await desk["http"].get("/abdm/hfr/registrations/76803")).json()
    assert saved["basic"]["address"]["sub_district_code"] == "4194"
    assert saved["basic"]["timings"][0] == {"days": ["Mon", "Tue"], "hours": "9:00 AM - 6:00 PM"}
    assert saved["additional"]["nin"] == "1234" and saved["additional"]["general"]["pharmacy"] == "YALL"
    assert saved["detailed"]["infrastructure"]["ipd_beds_with_oxygen"] == 5
    assert saved["submitted_at"] is not None


async def test_the_photos_go_to_hfr_and_are_never_kept(desk):
    await _sign_in(desk)
    await _register(desk)
    saved = (await desk["http"].get("/abdm/hfr/registrations/76803")).json()
    assert {"board_photo", "building_photo", "address_proofs"}.isdisjoint(saved["basic"])
    assert PNG not in json.dumps(saved)


async def test_an_edit_resends_basic_details_under_the_same_tracking_id(desk):
    """HFR-064 to 092: the basic-details update is basic-information with the tracking id."""
    await _sign_in(desk)
    await _register(desk)
    edited = _basic(tracking_id="76803", name="HealthDoc Sandbox Test Hospital East",
                    operational_status="TC")
    response = await desk["http"].post("/abdm/hfr/registration/basic", json=edited)
    assert response.status_code == 200, response.text
    path, body, headers = desk["fake"].calls[-1]
    assert path == "/v1.5/facility/basic-information" and headers == {"x-hprid-auth": HPR_NUMBER}
    assert body["trackingId"] == "76803"
    assert body["facilityInformation"]["facilityName"] == "HealthDoc Sandbox Test Hospital East"
    listed = (await desk["http"].get("/abdm/hfr/registrations")).json()["registrations"]
    assert len(listed) == 1, "an edit updates the facility's row, not a second one"
    saved = (await desk["http"].get("/abdm/hfr/registrations/76803")).json()
    assert saved["basic"]["name"] == "HealthDoc Sandbox Test Hospital East"
    assert saved["basic"]["operational_status"] == "TC"
    assert saved["facility_id"] == "IN0610090166", "the facility id survives the edit"
    audits = (await desk["db"].execute(select(AuditLog).where(
        AuditLog.resource_type == "hfr_registration").order_by(AuditLog.created_at))).scalars().all()
    assert audits[-1].new_value["edit"] is True


async def test_another_facilitys_registration_is_not_found(desk):
    await _sign_in(desk)
    await _register(desk)
    other = Facility(id=uuid.uuid4(), code=f"HR{uuid.uuid4().hex[:4]}", name="Other", state_code="MH")
    desk["db"].add(other)
    await desk["db"].flush()
    row = (await desk["db"].execute(select(hfr_models.AbdmHfrRegistration))).scalar_one()
    row.facility_id = other.id
    await desk["db"].flush()
    missing = await desk["http"].get("/abdm/hfr/registrations/76803")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "hfr_registration_not_found"
    assert (await desk["http"].get("/abdm/hfr/registrations")).json() == {"registrations": []}


async def test_a_tracking_id_is_digits(desk):
    assert (await desk["http"].get("/abdm/hfr/registrations/76803x")).status_code == 422

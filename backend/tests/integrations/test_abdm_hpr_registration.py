"""Registration of the signed-in professional in HPR (M4 HPR-018 to 079).

The practitioner follows NHA's Register Healthcare Professional API document
(sandbox, "newly updated") and Master Data workbook; the KYC comes with the
HPR login (hpr_login.kyc). Every value is synthetic.
"""

import base64
import json
import time
import uuid
from datetime import date

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.integrations.abdm.client import AbdmRejected, AbdmUnavailable
from app.integrations.abdm.hfr import client, hpr_login, hpr_router

pytestmark = pytest.mark.asyncio
PDF = base64.b64encode(b"%PDF-1.7 synthetic certificate").decode()
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n synthetic").decode()
REGISTER = "/apis/v1/doctors/register-professional-new"
UPDATE = "/apis/v1/doctors/update-professional-new"
KYC = {"name": "Asha Kumari Verma", "first_name": "Asha", "middle_name": "Kumari", "last_name": "Verma",
       "gender": "F", "birth_date": "1990-04-07", "address": "1 Synthetic Lane, Pune City", "state_name": "Maharashtra",
       "district_name": "Pune", "pincode": "411001", "mobile": "9876543210", "email": "asha@example.org",
       "photo": "a3ljLXBob3Rv", "state_code": "27", "district_code": "490"}
MASTERS = {
    "/apis/v1/masters/states": [{"id": 20, "name": "Maharashtra", "isoCode": "27"}],
    "/apis/v1/masters/district/20": [{"id": 499, "districtName": "Washim", "isoCode": "497"}],
    "/apis/v1/masters/sub-districts/499": [{"id": 2910, "subDistrictName": "Karanja", "isoCode": "3997"}],
}


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


class _Hpr:
    def __init__(self):
        self.calls = []
        self.answers = dict(MASTERS)

    async def call(self, method, path, *, json=None, headers=None):
        self.calls.append((method, path, json, headers))
        answer = self.answers.get(path)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def sent(self, path):
        return next(c for c in reversed(self.calls) if c[1] == path)


@pytest_asyncio.fixture
async def desk(monkeypatch):
    redis, fake = _Redis(), _Hpr()
    monkeypatch.setattr(hpr_login, "get_redis", lambda: redis)
    monkeypatch.setattr(client, "call", fake.call)
    app = FastAPI()
    app.include_router(hpr_router.router)
    caller = DbUser(id=uuid.uuid4(), keycloak_sub="sub-admin", username="admin", facility_id=uuid.uuid4(), roles=["admin"])
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub=caller.keycloak_sub, roles=["admin"])
    app.dependency_overrides[get_current_db_user] = lambda: caller
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as http:
        yield {"fake": fake, "http": http, "caller": caller}


async def _sign_in(desk, kyc=KYC):
    token = _jwt(hprId="asha.verma@hpr.abdm", hprIdNumber="71-0000-0000-0002", exp=int(time.time()) + 900)
    await hpr_login._keep(desk["caller"].facility_id, desk["caller"].id, "asha.verma@hpr.abdm", token, kyc=kyc)
    return token


def _form(**change):
    body = {
        "salutation": 1, "category": 1, "subcategory": 4, "languages": [1, 2],
        "father_name": "Ramesh Verma",
        "registration": {
            "council": 23, "number": "MMC-2015-123", "registered_on": "2015-06-01",
            "certificate": {"file_type": "pdf", "content": PDF},
            "qualifications": [{"degree": 4079, "state": "20", "college": 1022, "university": 6372, "year": 2014,
                                "month": "February", "certificate": {"file_type": "pdf", "content": PDF}}],
        },
        "work": {"working": True, "purpose": "Practice", "status": "PRIVATE", "facility_id": "IN2710005985",
                 "department": "General Medicine", "designation": "Consultant"},
    }
    body.update(change)
    return body


async def test_registration_needs_the_professionals_hpr_login(desk):
    response = await desk["http"].post("/abdm/hpr/professional", json=_form())
    assert response.status_code == 409 and response.json()["detail"]["code"] == "hpr_login_required"
    assert desk["fake"].calls == []


async def test_a_login_without_aadhaar_kyc_is_sent_to_verify_aadhaar(desk):
    await _sign_in(desk, kyc=None)
    response = await desk["http"].post("/abdm/hpr/professional", json=_form())
    assert response.status_code == 409 and response.json()["detail"]["code"] == "hpr_kyc_required"
    assert all(c[1] != REGISTER for c in desk["fake"].calls)


async def test_the_profile_shows_aadhaars_details_without_the_full_mobile(desk):
    await _sign_in(desk)
    profile = (await desk["http"].get("/abdm/hpr/profile")).json()
    assert profile["name"] == "Asha Kumari Verma" and profile["birth_date"] == "1990-04-07"
    assert profile["mobile_hint"] == "3210" and "mobile" not in profile
    assert profile["hpr_id_number"] == "71-0000-0000-0002"
    assert all(c[1] != "/v1/account/information" for c in desk["fake"].calls)


async def test_registration_follows_nhas_document(desk):
    """HPR-018/027-029/037: token in the body, KYC from the login, NHA's codes."""
    token = await _sign_in(desk)
    desk["fake"].answers[REGISTER] = {"referenceNumber": "REF1", "status": "SUBMITTED",
                                      "message": "Registered", "hprId": "asha.verma@hpr.abdm"}
    response = await desk["http"].post("/abdm/hpr/professional", json=_form(first_name="Somebody Else"))
    assert response.status_code == 200, response.text
    assert response.json()["reference_number"] == "REF1"
    _, _, body, headers = desk["fake"].sent(REGISTER)
    assert headers is None, "Authorization stays the gateway token; the professional's rides in the body"
    assert body["hprToken"] == token
    p = body["practitioner"]
    personal = p["personalInformation"]
    assert (personal["firstName"], personal["middleName"], personal["lastName"]) == ("Asha", "Kumari", "Verma")
    assert personal["gender"] == "F" and personal["dateOfBirth"] == "1990-04-07"
    assert personal["salutation"] == 1 and personal["languagesSpoken"] == "1,2"
    assert personal["category"] == "", "private work: empty, as NHA requires"
    assert p["addressAsPerKYC"] == "1 Synthetic Lane, Pune City" and p["officialMobile"] == "9876543210"
    assert p["profilePhoto"] == "a3ljLXBob3Rv" and p["healthProfessionalType"] == "doctor"
    assert p["communicationAddress"]["isCommunicationAddressAsPerKYC"] == "1"
    data = p["registrationAcademic"]["registrationData"][0]
    assert p["registrationAcademic"]["category"] == 1
    assert data["categoryId"] == 4, "Ayurveda as registration's system of medicine (4), not HPID's subcategory (3)"
    assert data["registrationCertificate"] == {"fileType": "pdf", "data": PDF}
    assert data["isPermanentOrRenewable"] == "Permanent" and data["isNameDifferentInCertificate"] == "0"
    q = data["qualifications"][0]
    assert q["state"] == "27", "HPR's ISO code for the state, not its lookup id 20"
    assert (q["nameOfDegreeOrDiplomaObtained"], q["college"], q["university"]) == (4079, 1022, 6372)
    work = p["currentWorkDetails"]
    assert (work["currentlyWorking"], work["purposeOfWork"], work["chooseWorkStatus"]) == ("1", "Practice", "0")
    assert work["facilityDeclarationData"]["facilityId"] == "IN2710005985"
    assert "ministry" not in work["facilityDeclarationData"]


async def test_central_government_work_names_its_ministry_and_carries_proof(desk):
    """HPR-074/075; NHA: Government 1, category "C", ministry for central."""
    await _sign_in(desk)
    desk["fake"].answers[REGISTER] = {"status": "SUBMITTED"}
    response = await desk["http"].post("/abdm/hpr/professional", json=_form(work={
        "working": True, "purpose": "Administrative", "status": "GOVERNMENT", "government_type": "CENTRAL",
        "ministry": "MinistryMOR ( Mo Railways )", "facility_id": "IN2710005985",
        "proof": {"file_type": "png", "content": PNG}}))
    assert response.status_code == 200, response.text
    p = desk["fake"].sent(REGISTER)[2]["practitioner"]
    assert p["personalInformation"]["category"] == "C"
    work = p["currentWorkDetails"]
    assert work["chooseWorkStatus"] == "1" and work["certificateAttachment"] == PNG
    assert work["facilityDeclarationData"]["ministry"] == {"ministry": "MinistryMOR ( Mo Railways )"}


async def test_state_government_and_both(desk):
    await _sign_in(desk)
    desk["fake"].answers[REGISTER] = {"status": "SUBMITTED"}
    await desk["http"].post("/abdm/hpr/professional", json=_form(work={
        "working": True, "purpose": "Practice", "status": "BOTH", "government_type": "STATE",
        "facility_id": "IN2710005985", "proof": {"file_type": "pdf", "content": PDF}}))
    p = desk["fake"].sent(REGISTER)[2]["practitioner"]
    assert p["personalInformation"]["category"] == "S" and p["currentWorkDetails"]["chooseWorkStatus"] == "2"


async def test_a_nurse_registration_has_no_renewal_and_uses_nurse_codes(desk):
    await _sign_in(desk)
    desk["fake"].answers[REGISTER] = {"status": "SUBMITTED"}
    response = await desk["http"].post("/abdm/hpr/professional", json=_form(category=2, subcategory=8))
    assert response.status_code == 200, response.text
    p = desk["fake"].sent(REGISTER)[2]["practitioner"]
    data = p["registrationAcademic"]["registrationData"][0]
    assert p["healthProfessionalType"] == "nurse" and data["categoryId"] == 8
    assert data["isPermanentOrRenewable"] == "" and data["renewableDueDate"] == ""


async def test_a_different_communication_address_carries_iso_codes(desk):
    """HPR-038 to 046."""
    await _sign_in(desk)
    desk["fake"].answers[UPDATE] = {"status": "UPDATED", "message": "Updated"}
    response = await desk["http"].post("/abdm/hpr/professional/update", json=_form(
        communication_address={"name": "Asha Verma", "address": "2 Clinic Road", "state": "20", "district": "499",
                               "sub_district": "2910", "pincode": "444505"}))
    assert response.status_code == 200, response.text
    comm = desk["fake"].sent(UPDATE)[2]["practitioner"]["communicationAddress"]
    assert comm["isCommunicationAddressAsPerKYC"] == "0"
    assert (comm["state"], comm["district"], comm["subDistrict"]) == ("27", "497", "3997")


async def test_a_place_hpr_does_not_list_is_refused(desk):
    await _sign_in(desk)
    form = _form()
    form["registration"]["qualifications"][0]["state"] = "99"
    response = await desk["http"].post("/abdm/hpr/professional", json=form)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "hpr_place_unknown"
    assert all(c[1] != REGISTER for c in desk["fake"].calls)


@pytest.mark.parametrize("change", [
    {"salutation": 4},
    {"category": 3},
    {"subcategory": 8},
    {"category": 2, "subcategory": 4},
    {"languages": []},
    {"work": {"working": False}},
    {"work": {"working": True, "purpose": "Practice", "status": "PRIVATE"}},
    {"work": {"working": True, "status": "PRIVATE", "facility_id": "IN2710005985"}},
    {"work": {"working": True, "purpose": "Practice", "status": "GOVERNMENT", "facility_id": "IN2710005985",
              "proof": {"file_type": "pdf", "content": PDF}}},
    {"work": {"working": True, "purpose": "Practice", "status": "GOVERNMENT", "government_type": "CENTRAL",
              "facility_id": "IN2710005985", "proof": {"file_type": "pdf", "content": PDF}}},
    {"work": {"working": True, "purpose": "Practice", "status": "GOVERNMENT", "government_type": "STATE",
              "facility_id": "IN2710005985"}},
    {"registration": {**_form()["registration"], "registered_on": "2999-01-01"}},
    {"registration": {**_form()["registration"], "renewable": True}},
    {"registration": {**_form()["registration"], "name_differs": True}},
    {"registration": {**_form()["registration"], "qualifications": []}},
    {"registration": {**_form()["registration"], "certificate": {"file_type": "pdf", "content": PNG}}},
    {"registration": {**_form()["registration"], "qualifications": [
        {**_form()["registration"]["qualifications"][0], "year": date.today().year + 1}]}},
])
async def test_the_workbook_rules_hold_before_hpr_is_asked(desk, change):
    """HPR-054 to 076, with NHA's codes."""
    await _sign_in(desk)
    response = await desk["http"].post("/abdm/hpr/professional", json=_form(**change))
    assert response.status_code == 422, response.text
    assert all(c[1] != REGISTER for c in desk["fake"].calls)


async def test_a_reason_for_not_working_is_sent_as_given(desk):
    await _sign_in(desk)
    desk["fake"].answers[REGISTER] = {"status": "SUBMITTED"}
    await desk["http"].post("/abdm/hpr/professional", json=_form(work={"working": False, "reason_not_working": "Retired"}))
    work = desk["fake"].sent(REGISTER)[2]["practitioner"]["currentWorkDetails"]
    assert (work["currentlyWorking"], work["reasonForNotWorking"], work["purposeOfWork"]) == ("0", "Retired", "")
    assert "facilityDeclarationData" not in work


async def test_hprs_refusal_is_shown_and_never_resent(desk):
    await _sign_in(desk)
    desk["fake"].answers[REGISTER] = AbdmRejected(422, {"code": "HIS-422", "details": [
        {"message": "Registration number already exists", "code": "HIS-1000"}]}, "rid")
    refused = await desk["http"].post("/abdm/hpr/professional", json=_form())
    assert refused.status_code == 400
    assert refused.json()["detail"]["messages"] == ["Registration number already exists"]
    desk["fake"].answers[REGISTER] = AbdmUnavailable("timeout")
    unavailable = await desk["http"].post("/abdm/hpr/professional", json=_form())
    assert unavailable.status_code == 503
    assert sum(c[1] == REGISTER for c in desk["fake"].calls) == 2, "one attempt per request, no silent resend"
    desk["fake"].answers[REGISTER] = {"error": {"message": "Invalid council"}, "status": "FAILED"}
    failed = await desk["http"].post("/abdm/hpr/professional", json=_form())
    assert failed.status_code == 400 and failed.json()["detail"]["messages"] == ["Invalid council"]


async def test_the_registered_profile_is_read_back_by_hpr_id_number(desk):
    """HPR-078; HPR nests practitioners one list deeper (NHA's document and 5 Oct live)."""
    await _sign_in(desk)
    desk["fake"].answers["/apis/v1/doctors/fetch-professional-info"] = {
        "Message": "Data fetched successfully", "practitioners": [[{"salutation": "Dr.", "name": "Asha"}]]}
    shown = (await desk["http"].get("/abdm/hpr/professional")).json()
    assert shown == {"practitioner": {"salutation": "Dr.", "name": "Asha"}}
    assert desk["fake"].sent("/apis/v1/doctors/fetch-professional-info")[2]["practitioner"]["id"] == "71-0000-0000-0002"

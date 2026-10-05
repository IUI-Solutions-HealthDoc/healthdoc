"""Registration of the signed-in professional in HPR (M4 HPR-018 to 079).

The practitioner shape is NHA's Postman example; the profile fields are HPR's
specification for /v1/account/information. Every value is synthetic.
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
PROFILE = {
    "hprIdNumber": "71-0000-0000-0002", "hprId": "asha.verma@hpr.abdm", "mobile": "9876543210",
    "firstName": "Asha", "middleName": "Kumari", "lastName": "Verma", "name": "Asha Kumari Verma",
    "yearOfBirth": "1990", "monthOfBirth": "4", "dayOfBirth": "7", "gender": "F", "email": "asha@example.org",
    "address": "1 Synthetic Lane, Pune", "kycPhoto": "a3ljLXBob3Rv", "stateName": "Maharashtra",
    "districtName": "Pune", "pincode": "411001", "categoryId": 1, "categorySubId": 1, "kycVerified": True,
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
        self.answers = {"/v1/account/information": PROFILE}

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


async def _sign_in(desk):
    token = _jwt(hprId="asha.verma@hpr.abdm", hprIdNumber="71-0000-0000-0002", exp=int(time.time()) + 900)
    await hpr_login._keep(desk["caller"].facility_id, desk["caller"].id, "asha.verma@hpr.abdm", token)
    return token


def _form(**change):
    body = {
        "salutation": 1, "category": 1, "subcategory": 1, "languages": [1, 2],
        "father_name": "Ramesh Verma",
        "registration": {
            "council": 23, "number": "MMC-2015-123", "registered_on": "2015-06-01",
            "certificate": {"file_type": "pdf", "content": PDF},
            "qualifications": [{"degree": 4060, "state": "20", "college": 1022, "university": 6372, "year": 2014,
                                "month": "February", "certificate": {"file_type": "pdf", "content": PDF}}],
        },
        "work": {"working": True, "status": "PRIVATE", "facility_id": "IN2710005985",
                 "department": "General Medicine", "designation": "Consultant"},
    }
    body.update(change)
    return body


async def test_registration_needs_the_professionals_hpr_login(desk):
    response = await desk["http"].post("/abdm/hpr/professional", json=_form())
    assert response.status_code == 409 and response.json()["detail"]["code"] == "hpr_login_required"
    assert desk["fake"].calls == []


async def test_the_profile_shows_aadhaars_details_without_the_full_mobile(desk):
    token = await _sign_in(desk)
    profile = (await desk["http"].get("/abdm/hpr/profile")).json()
    assert profile["name"] == "Asha Kumari Verma" and profile["birth_date"] == "1990-04-07"
    assert profile["mobile_hint"] == "3210" and "mobile" not in profile
    assert desk["fake"].sent("/v1/account/information")[3] == {"X-Token": f"Bearer {token}"}


async def test_registration_sends_aadhaars_names_not_the_browsers(desk):
    """HPR-018/027-029/037: the token rides in the body; names come from KYC."""
    token = await _sign_in(desk)
    desk["fake"].answers[REGISTER] = {"referenceNumber": "REF1", "status": "SUBMITTED",
                                      "message": "Registered", "hprId": "asha.verma@hpr.abdm"}
    response = await desk["http"].post("/abdm/hpr/professional", json=_form(first_name="Somebody Else"))
    assert response.status_code == 200, response.text
    assert response.json()["reference_number"] == "REF1"
    _, _, body, _ = desk["fake"].sent(REGISTER)
    assert body["hprToken"] == token
    p = body["practitioner"]
    personal = p["personalInformation"]
    assert (personal["firstName"], personal["middleName"], personal["lastName"]) == ("Asha", "Kumari", "Verma")
    assert personal["gender"] == "F" and personal["dateOfBirth"] == "1990-04-07"
    assert personal["salutation"] == 1 and personal["languagesSpoken"] == "1,2"
    assert personal["fatherName"] == "Ramesh Verma"
    assert p["addressAsPerKYC"] == "1 Synthetic Lane, Pune"
    assert p["profilePhoto"] == "a3ljLXBob3Rv" and p["healthProfessionalType"] == "doctor"
    assert p["communicationAddress"]["isCommunicationAddressAsPerKYC"] == "true"
    data = p["registrationAcademic"]["registrationData"][0]
    assert p["registrationAcademic"]["category"] == 1 and data["categoryId"] == 1
    assert data["registeredWithCouncil"] == 23 and data["registrationDate"] == "2015-06-01"
    assert data["registrationCertificate"] == {"fileType": "pdf", "data": PDF}
    assert data["isPermanentOrRenewable"] == "Permanent"
    q = data["qualifications"][0]
    assert (q["nameOfDegreeOrDiplomaObtained"], q["college"], q["university"]) == (4060, 1022, 6372)
    assert q["yearOfAwardingDegreeDiploma"] == "2014" and q["monthOfAwardingDegreeDiploma"] == "February"
    work = p["currentWorkDetails"]
    assert work["currentlyWorking"] == "1" and work["chooseWorkStatus"] == "2"
    assert work["facilityDeclarationData"]["facilityId"] == "IN2710005985"
    assert work["certificateAttachment"] == ""


async def test_an_update_is_the_same_form_on_hprs_update_call(desk):
    """HPR-079."""
    await _sign_in(desk)
    desk["fake"].answers[UPDATE] = {"status": "UPDATED", "message": "Updated"}
    response = await desk["http"].post("/abdm/hpr/professional/update", json=_form(
        communication_address={"name": "Asha Verma", "address": "2 Clinic Road", "state": "20", "district": "499",
                               "pincode": "444505"}))
    assert response.status_code == 200, response.text
    comm = desk["fake"].sent(UPDATE)[2]["practitioner"]["communicationAddress"]
    assert comm["isCommunicationAddressAsPerKYC"] == "false" and comm["district"] == "499"


@pytest.mark.parametrize("change", [
    {"salutation": 9},
    {"languages": []},
    {"work": {"working": False}},
    {"work": {"working": True, "status": "GOVERNMENT", "facility_id": "IN2710005985"}},
    {"work": {"working": True, "status": "PRIVATE"}},
    {"registration": {**_form()["registration"], "registered_on": "2999-01-01"}},
    {"registration": {**_form()["registration"], "renewable": True}},
    {"registration": {**_form()["registration"], "name_differs": True}},
    {"registration": {**_form()["registration"], "qualifications": []}},
    {"registration": {**_form()["registration"], "certificate": {"file_type": "pdf", "content": PNG}}},
    {"registration": {**_form()["registration"], "qualifications": [
        {**_form()["registration"]["qualifications"][0], "year": date.today().year + 1}]}},
])
async def test_the_workbook_rules_hold_before_hpr_is_asked(desk, change):
    """HPR-054 to 076."""
    await _sign_in(desk)
    response = await desk["http"].post("/abdm/hpr/professional", json=_form(**change))
    assert response.status_code == 422, response.text
    assert all(c[1] != REGISTER for c in desk["fake"].calls)


async def test_government_work_carries_its_proof(desk):
    """HPR-075."""
    await _sign_in(desk)
    desk["fake"].answers[REGISTER] = {"status": "SUBMITTED"}
    await desk["http"].post("/abdm/hpr/professional", json=_form(work={
        "working": True, "status": "BOTH", "facility_id": "IN2710005985", "proof": {"file_type": "png", "content": PNG}}))
    work = desk["fake"].sent(REGISTER)[2]["practitioner"]["currentWorkDetails"]
    assert work["chooseWorkStatus"] == "3" and work["certificateAttachment"] == PNG


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


async def test_a_profile_without_an_aadhaar_name_stops_registration(desk):
    await _sign_in(desk)
    desk["fake"].answers["/v1/account/information"] = {"hprId": "x@hpr.abdm"}
    response = await desk["http"].post("/abdm/hpr/professional", json=_form())
    assert response.status_code == 502 and response.json()["detail"]["code"] == "hpr_profile_missing"
    assert all(c[1] != REGISTER for c in desk["fake"].calls)


async def test_the_registered_profile_is_read_back_by_hpr_id_number(desk):
    """HPR-078; HPR nests practitioners one list deeper than its example."""
    await _sign_in(desk)
    desk["fake"].answers["/apis/v1/doctors/fetch-professional-info"] = {
        "message": "Data fetched successfully", "practitioners": [[{"salutation": "Dr", "name": "Asha"}]]}
    shown = (await desk["http"].get("/abdm/hpr/professional")).json()
    assert shown == {"practitioner": {"salutation": "Dr", "name": "Asha"}}
    assert desk["fake"].sent("/apis/v1/doctors/fetch-professional-info")[2]["practitioner"]["id"] == "71-0000-0000-0002"

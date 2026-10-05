"""HPID creation (M4 HPR-002 to 011) and HPR master data.

The Aadhaar is verified on NHA's own page (generateLink, isAuthenticated,
verifyOTP {txnId}); checkHpIdAccountExist then returns the KYC and, for an
existing HPID, its login. Shapes are the sandbox's own where it has answered
(5 Oct 2026); padding is PKCS#1 v1.5, which HPR decrypts.
"""

import base64
import json
import time
import uuid

import httpx
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI

from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.integrations.abdm.client import AbdmRejected
from app.integrations.abdm.hfr import client, hpid, hpr_login, hpr_router

pytestmark = pytest.mark.asyncio
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
NHA_PAGE = "https://healthidbeta.abdm.gov.in/abdm/aadhaar/gateway/auth?l=synthetic"
VERIFIED = {  # verifyOTP {txnId} after NHA's page, as NHA's sandbox document shows it
    "txnId": "txn-2", "mobileNumber": "******4321", "photo": "cGhvdG8=", "name": "Asha Kumari Verma",
    "gender": "F", "dob": "1990-04-07",
    "address": {"house": "1", "street": "Synthetic Lane", "district": "Pune", "state": "Maharashtra", "pincode": "411001"},
}
KYC_ANSWER = {
    "token": "", "hprIdNumber": "", "txnId": "txn-3", "name": "Asha Kumari Verma", "gender": "F",
    "yearOfBirth": "1990", "monthOfBirth": "4", "dayOfBirth": "7", "firstName": "Asha", "middleName": "Kumari",
    "lastName": "Verma", "stateCode": "27", "districtCode": "490", "stateName": "Maharashtra",
    "districtName": "Pune", "address": "1 Synthetic Lane, Pune City", "pincode": "411001", "profilePhoto": "cGhvdG8=",
}


def _jwt(**claims) -> str:
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{part({'alg': 'RS512'})}.{part(claims)}.signature"


def _plain(sealed: str) -> str:
    return KEY.decrypt(base64.b64decode(sealed), padding.PKCS1v15()).decode()


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
        self.answers = {"/api/v1/auth/cert": PEM}

    async def call(self, method, path, *, json=None, headers=None):
        self.calls.append((method, path, json))
        answer = self.answers.get(path)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def body(self, path):
        return next(body for _, p, body in reversed(self.calls) if p == path)

    def paths(self):
        return [p for _, p, _ in self.calls if p != "/api/v1/auth/cert"]


@pytest_asyncio.fixture
async def desk(monkeypatch):
    redis, fake = _Redis(), _Hpr()
    monkeypatch.setattr(hpr_login, "get_redis", lambda: redis)
    monkeypatch.setattr(hpid, "get_redis", lambda: redis)
    monkeypatch.setattr(client, "call", fake.call)
    app = FastAPI()
    app.include_router(hpr_router.router)
    caller = DbUser(id=uuid.uuid4(), keycloak_sub="sub-admin", username="admin",
                    facility_id=uuid.uuid4(), roles=["admin"])
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub=caller.keycloak_sub, roles=["admin"])
    app.dependency_overrides[get_current_db_user] = lambda: caller
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as http:
        yield {"fake": fake, "http": http, "caller": caller, "app": app}


def _answers(fake, *, exists=None):
    fake.answers.update({
        "/aadhaar/generateLink": {"status": "URL GENERATED", "txnId": "txn-1", "url": NHA_PAGE},
        "/aadhaar/isAuthenticated": True,
        "/v2/registration/aadhaar/verifyOTP": VERIFIED,
        "/v1/registration/aadhaar/checkHpIdAccountExist": exists or KYC_ANSWER,
        "/v1/registration/aadhaar/hpid/suggestion": ["asha.verma", "ashaverma"],
        "/apis/v1/masters/states": [{"id": 20, "name": "Maharashtra", "isoCode": "27"}],
        "/apis/v1/masters/district/20": [{"id": 499, "districtName": "Pune", "isoCode": "490"}],
    })


async def _verified(desk):
    _answers(desk["fake"])
    started = (await desk["http"].post("/abdm/hpr/hpid/link")).json()
    checked = await desk["http"].post("/abdm/hpr/hpid/link/check", json={"session_id": started["session_id"]})
    return started["session_id"], checked


async def test_the_aadhaar_is_verified_on_nhas_own_page(desk):
    """HPR-002 to 007 happen on NHA's page; HealthDoc never sees the Aadhaar."""
    _answers(desk["fake"])
    response = await desk["http"].post("/abdm/hpr/hpid/link")
    assert response.status_code == 200, response.text
    assert response.json()["url"] == NHA_PAGE
    assert desk["fake"].body("/aadhaar/generateLink") == {"scopes": ["nhpr-register"], "source": "NHPR"}


async def test_until_nha_says_authenticated_nothing_else_is_asked(desk):
    _answers(desk["fake"])
    desk["fake"].answers["/aadhaar/isAuthenticated"] = False
    started = (await desk["http"].post("/abdm/hpr/hpid/link")).json()
    waiting = await desk["http"].post("/abdm/hpr/hpid/link/check", json={"session_id": started["session_id"]})
    assert waiting.json() == {"authenticated": False}
    assert desk["fake"].paths() == ["/aadhaar/generateLink", "/aadhaar/isAuthenticated"]


async def test_a_waiting_nha_page_is_handed_back_not_replaced(desk):
    """5 Oct 2026: the desk reloaded, opened a second link and kept asking about
    it while NHA had confirmed the first."""
    _answers(desk["fake"])
    first = (await desk["http"].post("/abdm/hpr/hpid/link")).json()
    desk["fake"].answers["/aadhaar/generateLink"] = {"status": "URL GENERATED", "txnId": "txn-9", "url": NHA_PAGE + "2"}
    again = (await desk["http"].post("/abdm/hpr/hpid/link")).json()
    assert again == first
    assert desk["fake"].paths().count("/aadhaar/generateLink") == 1
    await desk["http"].post("/abdm/hpr/hpid/link/check", json={"session_id": again["session_id"]})
    assert desk["fake"].body("/aadhaar/isAuthenticated") == {"txnId": "txn-1"}


async def test_cancel_opens_a_new_nha_page(desk):
    _answers(desk["fake"])
    first = (await desk["http"].post("/abdm/hpr/hpid/link")).json()
    desk["fake"].answers["/aadhaar/generateLink"] = {"status": "URL GENERATED", "txnId": "txn-9", "url": NHA_PAGE + "2"}
    fresh = (await desk["http"].post("/abdm/hpr/hpid/link", json={"fresh": True})).json()
    assert fresh["session_id"] != first["session_id"] and fresh["url"] == NHA_PAGE + "2"


async def test_another_admin_gets_their_own_nha_page(desk):
    _answers(desk["fake"])
    first = (await desk["http"].post("/abdm/hpr/hpid/link")).json()
    other = DbUser(id=uuid.uuid4(), keycloak_sub="sub-other", username="other",
                   facility_id=desk["caller"].facility_id, roles=["admin"])
    desk["app"].dependency_overrides[get_current_db_user] = lambda: other
    theirs = (await desk["http"].post("/abdm/hpr/hpid/link")).json()
    assert theirs["session_id"] != first["session_id"]


async def test_after_nhas_page_the_kyc_and_suggestions_come_back(desk):
    _, checked = await _verified(desk)
    body = checked.json()
    assert body["authenticated"] is True and body["existing"] is False
    assert body["suggestions"] == ["asha.verma", "ashaverma"]
    kyc = body["kyc"]
    assert (kyc["name"], kyc["gender"], kyc["birth_date"]) == ("Asha Kumari Verma", "F", "1990-04-07")
    assert kyc["address"] == "1, Synthetic Lane, Pune, Maharashtra", "verifyOTP's address object comes first"
    assert "mobile" not in kyc
    assert desk["fake"].body("/v2/registration/aadhaar/verifyOTP") == {"txnId": "txn-1"}
    assert desk["fake"].body("/v1/registration/aadhaar/checkHpIdAccountExist") == {"txnId": "txn-2"}
    assert desk["fake"].body("/v1/registration/aadhaar/hpid/suggestion") == {"txnId": "txn-3"}


async def test_hprs_refusal_is_passed_on(desk):
    _answers(desk["fake"])
    desk["fake"].answers["/v2/registration/aadhaar/verifyOTP"] = AbdmRejected(422, {
        "code": "HIS-422", "details": [{"message": "Aadhaar verification is pending. Please complete it to continue.",
                                        "code": "HIS-2099"}]}, "rid")
    started = (await desk["http"].post("/abdm/hpr/hpid/link")).json()
    refused = await desk["http"].post("/abdm/hpr/hpid/link/check", json={"session_id": started["session_id"]})
    assert refused.status_code == 400
    assert refused.json()["detail"]["message"] == "Aadhaar verification is pending. Please complete it to continue."


async def test_an_existing_hpid_is_sent_to_hprs_login_and_its_kyc_joins_it(desk):
    """One HPID per person. The token beside it is not an HPR login: live on
    5 Oct 2026 register-professional refused it ("roles or category in Hrp
    token can not be empty/null"). The professional signs in through HPR's
    login, and the Aadhaar KYC joins that login."""
    identity = _jwt(hprId="asha.verma@hpr.abdm", hprIdNumber="71-0000-0000-0001", exp=int(time.time()) + 900)
    _answers(desk["fake"], exists={**KYC_ANSWER, "hprIdNumber": "71-0000-0000-0001", "hprId": "asha.verma@hpr.abdm",
                                   "token": identity})
    started = (await desk["http"].post("/abdm/hpr/hpid/link")).json()
    checked = (await desk["http"].post("/abdm/hpr/hpid/link/check", json={"session_id": started["session_id"]})).json()
    assert checked["existing"] is True and checked["signed_in"] is False
    assert checked["hpr_id"] == "asha.verma@hpr.abdm" and checked["hpr_id_number"] == "71-0000-0000-0001"
    assert await hpr_login.current(desk["caller"].facility_id, desk["caller"].id) is None
    assert "/v1/registration/aadhaar/hpid/suggestion" not in desk["fake"].paths()

    login = _jwt(hprId="asha.verma@hpr.abdm", hprIdNumber="71-0000-0000-0001", roles=["PROFESSIONAL"],
                 exp=int(time.time()) + 900)
    await hpr_login._keep(desk["caller"].facility_id, desk["caller"].id, "asha.verma@hpr.abdm", login)
    held = await hpr_login.current(desk["caller"].facility_id, desk["caller"].id)
    assert held is not None and held[1] == login
    kept = await hpr_login.kyc(desk["caller"].facility_id, desk["caller"].id)
    assert kept["first_name"] == "Asha" and kept["birth_date"] == "1990-04-07"


async def test_a_held_kyc_never_joins_another_professionals_login(desk):
    _answers(desk["fake"], exists={**KYC_ANSWER, "hprIdNumber": "71-0000-0000-0001", "hprId": "asha.verma@hpr.abdm"})
    started = (await desk["http"].post("/abdm/hpr/hpid/link")).json()
    await desk["http"].post("/abdm/hpr/hpid/link/check", json={"session_id": started["session_id"]})
    other = _jwt(hprId="ravi@hpr.abdm", hprIdNumber="71-0000-0000-0009", exp=int(time.time()) + 900)
    await hpr_login._keep(desk["caller"].facility_id, desk["caller"].id, "ravi@hpr.abdm", other)
    assert await hpr_login.kyc(desk["caller"].facility_id, desk["caller"].id) is None


async def test_a_password_login_carries_no_kyc_so_registration_asks_for_aadhaar(desk):
    token = _jwt(hprId="x@hpr.abdm", hprIdNumber="71-0000-0000-0003", exp=int(time.time()) + 900)
    await hpr_login._keep(desk["caller"].facility_id, desk["caller"].id, "x@hpr.abdm", token)
    response = await desk["http"].get("/abdm/hpr/profile")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "hpr_kyc_required"


async def test_a_mobile_that_is_not_aadhaars_gets_an_otp_and_can_be_changed(desk):
    """HPR-010/011."""
    session_id, _ = await _verified(desk)
    fake = desk["fake"]
    fake.answers["/v2/registration/aadhaar/demographicAuthViaMobile"] = {"verified": False}
    fake.answers["/v1/registration/aadhaar/generateMobileOTP"] = {"txnId": "txn-5", "mobileNumber": "9876543210"}
    fake.answers["/v1/registration/aadhaar/verifyMobileOTP"] = {"txnId": "txn-6"}
    sent = await desk["http"].post("/abdm/hpr/hpid/mobile", json={"session_id": session_id, "mobile": "9876543210"})
    assert sent.json() == {"mobile_verified": False, "otp_sent": True}
    assert _plain(fake.body("/v2/registration/aadhaar/demographicAuthViaMobile")["mobileNumber"]) == "9876543210"
    verified = await desk["http"].post("/abdm/hpr/hpid/mobile/verify", json={"session_id": session_id, "otp": "123456"})
    assert verified.json() == {"mobile_verified": True}
    assert _plain(fake.body("/v1/registration/aadhaar/verifyMobileOTP")["otp"]) == "123456"
    fake.answers["/v2/registration/aadhaar/demographicAuthViaMobile"] = {"verified": True}
    changed = await desk["http"].post("/abdm/hpr/hpid/mobile", json={"session_id": session_id, "mobile": "9876543211"})
    assert changed.json() == {"mobile_verified": True, "otp_sent": False}


def _create(session_id, **change):
    body = {"session_id": session_id, "hpr_id": "asha.verma", "email": "asha@example.org",
            "password": "Synthetic#Pass9", "category_code": 1, "subcategory_code": 1,
            "state_id": "20", "district_id": "499"}
    body.update(change)
    return body


async def test_the_hpid_is_created_with_iso_codes_and_keeps_the_kyc(desk):
    session_id, _ = await _verified(desk)
    fake = desk["fake"]
    fake.answers["/v2/registration/aadhaar/demographicAuthViaMobile"] = {"verified": True}
    await desk["http"].post("/abdm/hpr/hpid/mobile", json={"session_id": session_id, "mobile": "9876543210"})
    token = _jwt(hprId="asha.verma@hpr.abdm", hprIdNumber="71-0000-0000-0002", exp=int(time.time()) + 900)
    fake.answers["/v2/registration/aadhaar/createHprIdWithPreVerified"] = {
        "token": token, "hprIdNumber": "71-0000-0000-0002", "hprId": "asha.verma@hpr.abdm",
        "kycPhoto": "cGhvdG8=", "email": "asha@example.org"}
    created = await desk["http"].post("/abdm/hpr/hpid/create", json=_create(session_id, hpr_id="Asha.Verma"))
    assert created.status_code == 200, created.text
    sent = fake.body("/v2/registration/aadhaar/createHprIdWithPreVerified")
    assert (sent["stateCode"], sent["districtCode"]) == ("27", "490"), "HPR's ISO codes, not its lookup ids"
    assert sent["role"] == 1 and sent["hprId"] == "asha.verma"
    assert (sent["firstName"], sent["lastName"]) == ("Asha", "Verma")
    assert _plain(sent["password"]) == "Synthetic#Pass9" and _plain(sent["email"]) == "asha@example.org"
    kept = await hpr_login.kyc(desk["caller"].facility_id, desk["caller"].id)
    assert kept["mobile"] == "9876543210", "the verified communication mobile, not Aadhaar's masked one"


async def test_create_waits_for_a_verified_mobile(desk):
    session_id, _ = await _verified(desk)
    refused = await desk["http"].post("/abdm/hpr/hpid/create", json=_create(session_id))
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "hpid_mobile_unverified"


@pytest.mark.parametrize("password", ["Sh0rt!a", "nouppercase#1", "NoSpecial123", "Verma#Strong1"])
async def test_weak_passwords_never_reach_hpr(desk, password):
    session_id, _ = await _verified(desk)
    desk["fake"].answers["/v2/registration/aadhaar/demographicAuthViaMobile"] = {"verified": True}
    await desk["http"].post("/abdm/hpr/hpid/mobile", json={"session_id": session_id, "mobile": "9876543210"})
    response = await desk["http"].post("/abdm/hpr/hpid/create", json=_create(session_id, password=password))
    assert response.status_code in (400, 422), response.text
    assert "/v2/registration/aadhaar/createHprIdWithPreVerified" not in desk["fake"].paths()


async def test_another_admin_cannot_continue_this_session(desk):
    session_id, _ = await _verified(desk)
    other = DbUser(id=uuid.uuid4(), keycloak_sub="sub-other", username="other",
                   facility_id=desk["caller"].facility_id, roles=["admin"])
    desk["app"].dependency_overrides[get_current_db_user] = lambda: other
    response = await desk["http"].post("/abdm/hpr/hpid/mobile", json={"session_id": session_id, "mobile": "9876543210"})
    assert response.status_code == 404


def test_the_kyc_reads_an_address_string_too():
    """NHA's production document returns the address as a string."""
    kyc = hpid.kyc_from({"firstName": "Rahul", "lastName": "Sharma", "gender": "M", "yearOfBirth": "1990",
                         "monthOfBirth": "1", "dayOfBirth": "2", "address": "12A MG Road, Bengaluru"})
    assert kyc["address"] == "12A MG Road, Bengaluru" and kyc["birth_date"] == "1990-01-02"
    assert kyc["name"] == "Rahul Sharma"


# ----------------------------------------------------------------- master data


async def test_master_lists_come_back_as_code_and_label(desk):
    fake = desk["fake"]
    fake.answers["/apis/v1/masters/district/27"] = [{"id": 484, "stateId": 27, "districtName": "Amritsar"}]
    fake.answers["/hpid/get/categories?role=1"] = [
        {"code": 1, "name": "Doctor", "subCategories": [{"code": "1", "name": "Modern Medicine"}]}]
    fake.answers["/apis/v1/masters/languages"] = [{"id": 1, "name": " English "}]
    assert (await desk["http"].get("/abdm/hpr/master/districts?state_code=27")).json() == {
        "data": [{"code": "484", "label": "Amritsar"}]}
    assert (await desk["http"].get("/abdm/hpr/master/categories")).json() == {"data": [
        {"code": "1", "label": "Doctor", "subcategories": [{"code": "1", "label": "Modern Medicine"}]}]}
    assert (await desk["http"].get("/abdm/hpr/master/languages")).json()["data"] == [{"code": "1", "label": "English"}]


async def test_registration_options_are_nhas_published_codes(desk):
    options = (await desk["http"].get("/abdm/hpr/master/registration-options")).json()
    assert {o["code"]: o["label"] for o in options["salutations"]} == {"1": "Dr.", "2": "Mr.", "3": "Ms.", "0": "Do not specify"}
    assert options["not_working_reasons"] == ["Retired", "Voluntary Opt-Out", "Suspended"]
    assert options["purposes"] == ["Administrative", "Practice", "Teaching", "Research"]
    assert {o["code"] for o in options["categories"]} == {"1", "2", "6"}


async def test_courses_ask_for_every_course_only_when_told(desk):
    desk["fake"].answers["/apis/v1/masters/courses"] = [{"id": 4060, "name": "MBBS"}]
    await desk["http"].get("/abdm/hpr/master/courses?system_of_medicine=Modern%20Medicine")
    assert desk["fake"].body("/apis/v1/masters/courses")["qualificationCount"] == ""
    await desk["http"].get("/abdm/hpr/master/courses?system_of_medicine=Modern%20Medicine&all_courses=true")
    assert desk["fake"].body("/apis/v1/masters/courses")["qualificationCount"] == "1"


async def test_a_college_path_cannot_be_steered(desk):
    desk["fake"].answers["/apis/v1/masters/colleges/27/..%2Fx"] = []
    await desk["http"].get("/abdm/hpr/master/colleges?state_code=27&system_of_medicine=../x")
    assert desk["fake"].calls[-1][1] == "/apis/v1/masters/colleges/27/..%2Fx"
    assert (await desk["http"].get("/abdm/hpr/master/districts?state_code=27/../1")).status_code == 422

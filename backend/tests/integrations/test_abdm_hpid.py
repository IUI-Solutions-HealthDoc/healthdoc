"""HPID creation (M4 HPR-002 to 011) and HPR master data.

Shapes are the sandbox's own where it has answered (generateLink, the bare
false from isAuthenticated, HIS-2099 before authentication, every master list,
5 Oct 2026); the rest follow NHA's Postman and are marked as such in hpid.py.
"""

import base64
import time
import uuid

import httpx
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI

from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.integrations.abdm.client import AbdmRejected
from app.integrations.abdm.hfr import client, hpid, hpr_login
from app.integrations.abdm.hfr import hpr_router

pytestmark = pytest.mark.asyncio
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
NHA_PAGE = "https://healthidbeta.abdm.gov.in/abdm/aadhaar/gateway/auth?l=synthetic"


def _jwt(**claims) -> str:
    import json

    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{part({'alg': 'RS512'})}.{part(claims)}.signature"


def _plain(sealed: str) -> str:
    return KEY.decrypt(base64.b64decode(sealed), padding.OAEP(
        mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None)).decode()


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
        if callable(answer):
            answer = answer(json)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def body(self, path):
        return next(body for _, p, body in reversed(self.calls) if p == path)


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


def _kyc_answers(fake, *, existing=None):
    fake.answers.update({
        "/aadhaar/generateLink": {"status": "URL GENERATED", "txnId": "txn-1", "url": NHA_PAGE},
        "/aadhaar/isAuthenticated": True,
        "/v2/registration/aadhaar/verifyOTP": {
            "txnId": "txn-2", "name": "Asha Kumari Verma", "firstName": "Asha", "middleName": "Kumari",
            "lastName": "Verma", "gender": "F", "mobile": "******4321", "photo": "cGhvdG8=",
            "stateName": "Maharashtra", "districtName": "Pune"},
        "/v1/registration/aadhaar/checkHpIdAccountExist": existing or {"txnId": "txn-3", "new": True},
        "/v1/registration/aadhaar/hpid/suggestion": ["asha.verma", "ashaverma"],
    })


async def _verified(desk):
    _kyc_answers(desk["fake"])
    start = (await desk["http"].post("/abdm/hpr/hpid/start")).json()
    checked = await desk["http"].post("/abdm/hpr/hpid/check", json={"session_id": start["session_id"]})
    return start["session_id"], checked


async def test_hpid_starts_on_nhas_own_aadhaar_page(desk):
    """HPR-002: the Aadhaar number and its OTP are entered on NHA's page."""
    _kyc_answers(desk["fake"])
    response = await desk["http"].post("/abdm/hpr/hpid/start")
    assert response.status_code == 200, response.text
    assert response.json()["url"] == NHA_PAGE
    assert desk["fake"].calls[0] == ("POST", "/aadhaar/generateLink", {"scopes": ["nhpr-register"], "source": "NHPR"})


async def test_until_nha_says_authenticated_nothing_else_is_asked(desk):
    _kyc_answers(desk["fake"])
    desk["fake"].answers["/aadhaar/isAuthenticated"] = False
    start = (await desk["http"].post("/abdm/hpr/hpid/start")).json()
    waiting = await desk["http"].post("/abdm/hpr/hpid/check", json={"session_id": start["session_id"]})
    assert waiting.json() == {"authenticated": False}
    assert [p for _, p, _ in desk["fake"].calls] == ["/aadhaar/generateLink", "/aadhaar/isAuthenticated"]


async def test_after_authentication_the_kyc_and_suggestions_come_back(desk):
    session_id, checked = await _verified(desk)
    body = checked.json()
    assert body["authenticated"] is True
    assert body["kyc"]["first_name"] == "Asha" and body["kyc"]["last_name"] == "Verma"
    assert "mobile" not in body["kyc"], "only a hint of the Aadhaar mobile is shown"
    assert body["aadhaar_mobile_hint"] == "4321"
    assert body["suggestions"] == ["asha.verma", "ashaverma"]
    fake = desk["fake"]
    assert fake.body("/v1/registration/aadhaar/checkHpIdAccountExist") == {"txnId": "txn-2"}, \
        "each call continues the latest transaction id"
    assert fake.body("/v1/registration/aadhaar/hpid/suggestion") == {"txnId": "txn-3"}
    again = await desk["http"].post("/abdm/hpr/hpid/check", json={"session_id": session_id})
    assert again.json() == body
    assert sum(p == "/v2/registration/aadhaar/verifyOTP" for _, p, _ in fake.calls) == 1, "KYC is fetched once"


async def test_an_aadhaar_with_an_hpid_signs_in_instead(desk):
    _kyc_answers(desk["fake"], existing={"hprIdNumber": "71-0000-0000-0001", "new": False})
    start = (await desk["http"].post("/abdm/hpr/hpid/start")).json()
    checked = await desk["http"].post("/abdm/hpr/hpid/check", json={"session_id": start["session_id"]})
    assert checked.json() == {"authenticated": True, "existing_hpr_id": "71-0000-0000-0001"}
    gone = await desk["http"].post("/abdm/hpr/hpid/check", json={"session_id": start["session_id"]})
    assert gone.status_code == 404


async def test_a_mobile_that_is_not_aadhaars_gets_an_otp_and_travels_encrypted(desk):
    """HPR-010/011."""
    session_id, _ = await _verified(desk)
    fake = desk["fake"]
    fake.answers["/v2/registration/aadhaar/demographicAuthViaMobile"] = {"txnId": "txn-4", "verified": False}
    fake.answers["/v1/registration/aadhaar/generateMobileOTP"] = {"txnId": "txn-5"}
    fake.answers["/v1/registration/aadhaar/verifyMobileOTP"] = {"txnId": "txn-6"}
    sent = await desk["http"].post("/abdm/hpr/hpid/mobile", json={"session_id": session_id, "mobile": "9876543210"})
    assert sent.json() == {"mobile_verified": False, "otp_sent": True}
    demo = fake.body("/v2/registration/aadhaar/demographicAuthViaMobile")
    assert demo["txnId"] == "txn-3" and demo["mobileNumber"] != "9876543210"
    assert _plain(demo["mobileNumber"]) == "9876543210"
    assert fake.body("/v1/registration/aadhaar/generateMobileOTP")["txnId"] == "txn-4"
    verified = await desk["http"].post("/abdm/hpr/hpid/mobile/verify", json={"session_id": session_id, "otp": "123456"})
    assert verified.json() == {"mobile_verified": True}
    otp = fake.body("/v1/registration/aadhaar/verifyMobileOTP")
    assert _plain(otp["otp"]) == "123456" and otp["txnId"] == "txn-5"


def _create(session_id, **change):
    body = {"session_id": session_id, "hpr_id": "asha.verma", "email": "asha@example.org",
            "password": "Synthetic#Pass9", "category_code": 1, "subcategory_code": 1,
            "state_code": "20", "district_code": "499"}
    body.update(change)
    return body


async def test_the_hpid_is_created_and_signs_the_professional_in(desk):
    session_id, _ = await _verified(desk)
    fake = desk["fake"]
    fake.answers["/v2/registration/aadhaar/demographicAuthViaMobile"] = {"txnId": "txn-4", "verified": True}
    assert (await desk["http"].post("/abdm/hpr/hpid/mobile", json={
        "session_id": session_id, "mobile": "9876543210"})).json() == {"mobile_verified": True, "otp_sent": False}
    token = _jwt(hprId="asha.verma@hpr.abdm", hprIdNumber="71-0000-0000-0002", exp=int(time.time()) + 900)
    fake.answers["/v2/registration/aadhaar/createHprIdWithPreVerified"] = {
        "token": token, "hprIdNumber": "71-0000-0000-0002", "hprId": "asha.verma@hpr.abdm"}
    created = await desk["http"].post("/abdm/hpr/hpid/create", json=_create(session_id, hpr_id="Asha.Verma"))
    assert created.status_code == 200, created.text
    assert created.json()["hpr_id_number"] == "71-0000-0000-0002" and created.json()["logged_in"] is True
    sent = fake.body("/v2/registration/aadhaar/createHprIdWithPreVerified")
    assert sent["hprId"] == "asha.verma" and sent["txnId"] == "txn-4"
    assert (sent["firstName"], sent["middleName"], sent["lastName"]) == ("Asha", "Kumari", "Verma"), "names are Aadhaar's"
    assert sent["profilePhoto"] == "cGhvdG8=" and sent["sourceType"] == "AADHAAR"
    assert _plain(sent["password"]) == "Synthetic#Pass9" and _plain(sent["email"]) == "asha@example.org"
    held = await hpr_login.current(desk["caller"].facility_id, desk["caller"].id)
    assert held is not None and held[1] == token, "the new HPID's token is the HPR session registration uses"


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
    assert all(p != "/v2/registration/aadhaar/createHprIdWithPreVerified" for _, p, _ in desk["fake"].calls)


async def test_another_admin_cannot_continue_this_session(desk):
    session_id, _ = await _verified(desk)
    other = DbUser(id=uuid.uuid4(), keycloak_sub="sub-other", username="other",
                   facility_id=desk["caller"].facility_id, roles=["admin"])
    desk["app"].dependency_overrides[get_current_db_user] = lambda: other
    response = await desk["http"].post("/abdm/hpr/hpid/check", json={"session_id": session_id})
    assert response.status_code == 404


async def test_hprs_refusal_before_authentication_is_passed_on(desk):
    _kyc_answers(desk["fake"])
    desk["fake"].answers["/aadhaar/generateLink"] = AbdmRejected(422, {"code": "HIS-422"}, "rid")
    response = await desk["http"].post("/abdm/hpr/hpid/start")
    assert response.status_code == 502 and response.json()["detail"]["code"] == "hfr_rejected"


# ----------------------------------------------------------------- master data


async def test_master_lists_come_back_as_code_and_label(desk):
    fake = desk["fake"]
    fake.answers["/apis/v1/masters/district/27"] = [{"id": 484, "stateId": 27, "districtName": "Amritsar"}]
    fake.answers["/hpid/get/categories?role=1"] = [
        {"code": 1, "name": "Doctor", "subCategories": [{"code": "1", "name": "Modern Medicine"}]}]
    fake.answers["/apis/v1/masters/languages"] = [{"id": 1, "name": " English "}]
    assert (await desk["http"].get("/abdm/hpr/master/districts?state_id=27")).json() == {
        "data": [{"code": "484", "label": "Amritsar"}]}
    assert (await desk["http"].get("/abdm/hpr/master/categories")).json() == {"data": [
        {"code": "1", "label": "Doctor", "subcategories": [{"code": "1", "label": "Modern Medicine"}]}]}
    assert (await desk["http"].get("/abdm/hpr/master/languages")).json()["data"] == [{"code": "1", "label": "English"}]


async def test_courses_ask_for_every_course_only_when_told(desk):
    desk["fake"].answers["/apis/v1/masters/courses"] = [{"id": 4060, "name": "MBBS"}]
    await desk["http"].get("/abdm/hpr/master/courses?system_of_medicine=Modern%20Medicine")
    assert desk["fake"].body("/apis/v1/masters/courses")["qualificationCount"] == ""
    await desk["http"].get("/abdm/hpr/master/courses?system_of_medicine=Modern%20Medicine&all_courses=true")
    assert desk["fake"].body("/apis/v1/masters/courses")["qualificationCount"] == "1"


async def test_a_college_path_cannot_be_steered(desk):
    desk["fake"].answers["/apis/v1/masters/colleges/27/..%2Fx"] = []
    await desk["http"].get("/abdm/hpr/master/colleges?state_id=27&system_of_medicine=../x")
    assert desk["fake"].calls[-1][1] == "/apis/v1/masters/colleges/27/..%2Fx"
    assert (await desk["http"].get("/abdm/hpr/master/districts?state_id=27/../1")).status_code == 422

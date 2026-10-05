"""HPID creation in HealthDoc (M4 HPR-002 to 011) and HPR master data.

The flow is NHA's in-app one (Register Healthcare Professional API document,
production edition): generateOtp with the RSA-encrypted Aadhaar, verifyOTP,
checkHpIdAccountExist for the KYC. Answers below follow NHA's documented
shapes; padding is PKCS#1 v1.5, which HPR decrypts (5 Oct live).
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
from app.common.db import get_db
from app.integrations.abdm.client import AbdmRejected
from app.integrations.abdm.hfr import client, hpid, hpr_login, hpr_router

pytestmark = pytest.mark.asyncio
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
AADHAAR = "234567890123"  # synthetic
KYC_ANSWER = {
    "token": "", "hprIdNumber": "", "txnId": "txn-3", "name": "Asha Kumari Verma", "gender": "F",
    "yearOfBirth": "1990", "monthOfBirth": "4", "dayOfBirth": "7", "firstName": "Asha", "middleName": "Kumari",
    "lastName": "Verma", "stateCode": "27", "districtCode": "490", "stateName": "Maharashtra",
    "districtName": "Pune", "address": "1 Synthetic Lane, Pune City", "pincode": "411001",
    "profilePhoto": "cGhvdG8=", "mobile": "******4321",
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
    redis, fake, audit = _Redis(), _Hpr(), []
    monkeypatch.setattr(hpr_login, "get_redis", lambda: redis)
    monkeypatch.setattr(hpid, "get_redis", lambda: redis)
    monkeypatch.setattr(client, "call", fake.call)

    async def check(captcha_id, answer):
        return captcha_id == "cap-1" and answer == "AB3CD"
    monkeypatch.setattr(hpr_router.captcha, "check", check)

    async def write(db, **values):
        audit.append(values)
    monkeypatch.setattr(hpr_router, "write_audit_log", write)

    class _Db:
        async def commit(self):
            pass

    app = FastAPI()
    app.include_router(hpr_router.router)
    caller = DbUser(id=uuid.uuid4(), keycloak_sub="sub-admin", username="admin",
                    facility_id=uuid.uuid4(), roles=["admin"])
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub=caller.keycloak_sub, roles=["admin"])
    app.dependency_overrides[get_current_db_user] = lambda: caller
    app.dependency_overrides[get_db] = lambda: _Db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as http:
        yield {"fake": fake, "http": http, "caller": caller, "app": app, "audit": audit}


def _aadhaar(**change):
    body = {"aadhaar": AADHAAR, "consent_accepted": True, "consent_version": hpr_router.HPID_CONSENT_VERSION,
            "captcha_id": "cap-1", "captcha_answer": "AB3CD"}
    body.update(change)
    return body


def _answers(fake, *, exists=None):
    fake.answers.update({
        hpid.GENERATE_OTP: {"txnId": "txn-1", "mobileNumber": "******4321"},
        "/v2/registration/aadhaar/verifyOTP": {"txnId": "txn-2", "mobileNumber": None},
        "/v1/registration/aadhaar/checkHpIdAccountExist": exists or KYC_ANSWER,
        "/v1/registration/aadhaar/hpid/suggestion": ["asha.verma", "ashaverma"],
        "/apis/v1/masters/states": [{"id": 20, "name": "Maharashtra", "isoCode": "27"}],
        "/apis/v1/masters/district/20": [{"id": 499, "districtName": "Pune", "isoCode": "490"}],
    })


async def _verified(desk):
    _answers(desk["fake"])
    sent = (await desk["http"].post("/abdm/hpr/hpid/aadhaar", json=_aadhaar())).json()
    checked = await desk["http"].post("/abdm/hpr/hpid/aadhaar/verify", json={"session_id": sent["session_id"], "otp": "123456"})
    return sent["session_id"], checked


async def test_the_consent_shown_is_nhas_own(desk):
    consent = (await desk["http"].get("/abdm/hpr/hpid/consent")).json()
    assert consent["version"] == hpr_router.HPID_CONSENT_VERSION
    assert consent["text"].startswith("I, hereby declare that I am voluntarily sharing my Aadhaar Number / Virtual ID")
    assert "Healthcare Professional ID" in consent["text"]


async def test_the_aadhaar_otp_is_sent_in_healthdoc_after_consent_and_captcha(desk):
    """HPR-002 to 007: no redirect; the Aadhaar travels encrypted, never plain."""
    _answers(desk["fake"])
    response = await desk["http"].post("/abdm/hpr/hpid/aadhaar", json=_aadhaar())
    assert response.status_code == 200, response.text
    assert response.json()["masked_mobile"] == "******4321"
    sent = desk["fake"].body(hpid.GENERATE_OTP)
    assert sent["aadhaar"] != AADHAAR and _plain(sent["aadhaar"]) == AADHAAR
    assert desk["audit"][0]["resource_type"] == "hpid_consent"
    assert AADHAAR not in json.dumps(desk["audit"], default=str), "the Aadhaar number is never recorded"


@pytest.mark.parametrize("change", [
    {"consent_accepted": False}, {"consent_version": "old"}, {"aadhaar": "123456789012"},
    {"aadhaar": "23456789012"}, {"captcha_answer": "WRONG"},
])
async def test_without_consent_captcha_or_a_valid_number_no_otp_is_sent(desk, change):
    _answers(desk["fake"])
    response = await desk["http"].post("/abdm/hpr/hpid/aadhaar", json=_aadhaar(**change))
    assert response.status_code in (400, 422), response.text
    assert desk["fake"].paths() == []


async def test_hprs_reason_for_refusing_an_aadhaar_is_shown(desk):
    _answers(desk["fake"])
    desk["fake"].answers[hpid.GENERATE_OTP] = AbdmRejected(422, {
        "code": "HIS-422", "details": [{"message": "Aadhaar Number/Virtual ID is invalid.", "code": "HIS-2001"}]}, "rid")
    response = await desk["http"].post("/abdm/hpr/hpid/aadhaar", json=_aadhaar())
    assert response.status_code == 400
    assert response.json()["detail"]["message"] == "Aadhaar Number/Virtual ID is invalid."


async def test_resend_uses_hprs_ciphertext_not_the_number(desk):
    """HPR-008: NHA resends with the same call."""
    _answers(desk["fake"])
    sent = (await desk["http"].post("/abdm/hpr/hpid/aadhaar", json=_aadhaar())).json()
    first = desk["fake"].body(hpid.GENERATE_OTP)["aadhaar"]
    resent = await desk["http"].post("/abdm/hpr/hpid/aadhaar/resend", json={"session_id": sent["session_id"]})
    assert resent.status_code == 200, resent.text
    assert desk["fake"].body(hpid.GENERATE_OTP)["aadhaar"] == first


async def test_after_the_otp_the_kyc_and_suggestions_come_back(desk):
    session_id, checked = await _verified(desk)
    body = checked.json()
    assert body["existing"] is False and body["suggestions"] == ["asha.verma", "ashaverma"]
    kyc = body["kyc"]
    assert (kyc["first_name"], kyc["last_name"], kyc["gender"], kyc["birth_date"]) == ("Asha", "Verma", "F", "1990-04-07")
    assert kyc["address"] == "1 Synthetic Lane, Pune City" and "mobile" not in kyc
    verify = desk["fake"].body("/v2/registration/aadhaar/verifyOTP")
    assert verify["txnId"] == "txn-1" and verify["domainName"] == "@hpr.abdm" and verify["idType"] == "hpr_id"
    assert _plain(verify["otp"]) == "123456"
    assert desk["fake"].body("/v1/registration/aadhaar/checkHpIdAccountExist") == {"txnId": "txn-2"}
    assert desk["fake"].body("/v1/registration/aadhaar/hpid/suggestion") == {"txnId": "txn-3"}


async def test_an_existing_hpid_is_signed_in_with_its_kyc(desk):
    """One HPID per person; HPR hands over the existing one's login."""
    token = _jwt(hprId="asha.verma@hpr.abdm", hprIdNumber="71-0000-0000-0001", exp=int(time.time()) + 900)
    _answers(desk["fake"], exists={**KYC_ANSWER, "hprIdNumber": "71-0000-0000-0001", "hprId": "asha.verma@hpr.abdm",
                                   "token": token})
    sent = (await desk["http"].post("/abdm/hpr/hpid/aadhaar", json=_aadhaar())).json()
    checked = (await desk["http"].post("/abdm/hpr/hpid/aadhaar/verify", json={"session_id": sent["session_id"], "otp": "123456"})).json()
    assert checked["existing"] is True and checked["signed_in"] is True
    assert checked["hpr_id_number"] == "71-0000-0000-0001"
    held = await hpr_login.current(desk["caller"].facility_id, desk["caller"].id)
    assert held is not None and held[1] == token
    kept = await hpr_login.kyc(desk["caller"].facility_id, desk["caller"].id)
    assert kept["first_name"] == "Asha" and kept["birth_date"] == "1990-04-07"
    profile = (await desk["http"].get("/abdm/hpr/profile")).json()
    assert profile["name"] == "Asha Kumari Verma" and profile["hpr_id_number"] == "71-0000-0000-0001"
    assert "/v1/registration/aadhaar/hpid/suggestion" not in desk["fake"].paths()


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
    sent = await desk["http"].post("/abdm/hpr/hpid/mobile", json={"session_id": session_id, "mobile": "9876543210"})
    assert sent.json() == {"mobile_verified": False, "otp_sent": True}
    assert _plain(fake.body("/v2/registration/aadhaar/demographicAuthViaMobile")["mobileNumber"]) == "9876543210"
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
    assert kept["address"] == "1 Synthetic Lane, Pune City"


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


def test_the_kyc_reads_an_address_object_too():
    """NHA's sandbox document returns the address as an object."""
    kyc = hpid.kyc_from({"name": "Rahul Sharma", "gender": "M", "dob": "1990-01-01", "photo": "cA==",
                         "address": {"house": "12A", "street": "MG Road", "district": "Bangalore",
                                     "state": "Karnataka", "pincode": "560001"}})
    assert kyc["address"] == "12A, MG Road, Bangalore, Karnataka"
    assert (kyc["first_name"], kyc["last_name"], kyc["birth_date"], kyc["pincode"]) == ("Rahul", "Sharma", "1990-01-01", "560001")


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


# ----------------------------------------------------------------- NHA's page, the fallback


async def test_hprs_missing_transaction_offers_nhas_page(desk):
    """5 Oct live: verifyOTP cannot find the v2 generateOtp's transaction."""
    _answers(desk["fake"])
    desk["fake"].answers["/v2/registration/aadhaar/verifyOTP"] = AbdmRejected(422, {"code": "HIS-422", "details": [
        {"message": "Failed to retrieve aadhaar transaction details for txnID - 88e4d337", "code": "HIS-500"}]}, "rid")
    sent = (await desk["http"].post("/abdm/hpr/hpid/aadhaar", json=_aadhaar())).json()
    refused = await desk["http"].post("/abdm/hpr/hpid/aadhaar/verify", json={"session_id": sent["session_id"], "otp": "123456"})
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "hpid_inapp_unavailable"


async def test_nhas_page_waits_then_continues_like_the_in_app_route(desk):
    _answers(desk["fake"])
    fake = desk["fake"]
    fake.answers["/aadhaar/generateLink"] = {"status": "URL GENERATED", "txnId": "link-1",
                                             "url": "https://healthidbeta.abdm.gov.in/abdm/aadhaar/gateway/auth?l=x"}
    fake.answers["/aadhaar/isAuthenticated"] = False
    started = (await desk["http"].post("/abdm/hpr/hpid/link")).json()
    assert started["url"].startswith("https://healthidbeta.abdm.gov.in/")
    waiting = await desk["http"].post("/abdm/hpr/hpid/link/check", json={"session_id": started["session_id"]})
    assert waiting.json() == {"authenticated": False}
    fake.answers["/aadhaar/isAuthenticated"] = True
    fake.answers["/v2/registration/aadhaar/verifyOTP"] = {
        "txnId": "link-2", "name": "Asha Kumari Verma", "gender": "F", "dob": "1990-04-07", "photo": "cGhvdG8=",
        "address": {"house": "1", "street": "Synthetic Lane", "district": "Pune", "state": "Maharashtra", "pincode": "411001"}}
    done = (await desk["http"].post("/abdm/hpr/hpid/link/check", json={"session_id": started["session_id"]})).json()
    assert done["authenticated"] is True and done["existing"] is False
    assert done["kyc"]["birth_date"] == "1990-04-07" and done["suggestions"] == ["asha.verma", "ashaverma"]
    assert fake.body("/v2/registration/aadhaar/verifyOTP") == {"txnId": "link-1"}
    assert fake.body("/v1/registration/aadhaar/checkHpIdAccountExist") == {"txnId": "link-2"}
    # the session continues to the mobile step like the in-app route
    fake.answers["/v2/registration/aadhaar/demographicAuthViaMobile"] = {"verified": True}
    mobile = await desk["http"].post("/abdm/hpr/hpid/mobile", json={"session_id": started["session_id"], "mobile": "9876543210"})
    assert mobile.json() == {"mobile_verified": True, "otp_sent": False}


async def test_nhas_page_signs_in_an_existing_hpid_with_its_kyc(desk):
    token = _jwt(hprId="suprabha@hpr.abdm", hprIdNumber="71-8847-0813-4805", exp=int(time.time()) + 900)
    _answers(desk["fake"], exists={**KYC_ANSWER, "hprIdNumber": "71-8847-0813-4805", "hprId": "suprabha@hpr.abdm", "token": token})
    fake = desk["fake"]
    fake.answers["/aadhaar/generateLink"] = {"txnId": "link-1", "url": "https://healthidbeta.abdm.gov.in/x"}
    fake.answers["/aadhaar/isAuthenticated"] = True
    started = (await desk["http"].post("/abdm/hpr/hpid/link")).json()
    done = (await desk["http"].post("/abdm/hpr/hpid/link/check", json={"session_id": started["session_id"]})).json()
    assert done["existing"] is True and done["signed_in"] is True
    kept = await hpr_login.kyc(desk["caller"].facility_id, desk["caller"].id)
    assert kept["first_name"] == "Asha"

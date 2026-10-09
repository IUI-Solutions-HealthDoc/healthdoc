"""The official mobile and email are verified by OTP under the professional's
HPR login before registration (NHA's m4-verification journey). Live 6 Oct 2026,
HPR answered register-professional-new with a generic 500 without it.
Every value is synthetic."""

import base64
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
from app.integrations.abdm.hfr import client, hpid, hpr_contact, hpr_login, hpr_router
from tests.integrations.test_abdm_hpr_registration import KYC, MASTERS, REGISTER, _Hpr, _jwt, _Redis, _form

pytestmark = pytest.mark.asyncio
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
NO_CONTACT = {**KYC, "mobile": "", "email": ""}


def _plain(sealed: str) -> str:
    return KEY.decrypt(base64.b64decode(sealed), padding.PKCS1v15()).decode()


@pytest_asyncio.fixture
async def desk(monkeypatch):
    redis, fake = _Redis(), _Hpr()
    fake.answers.update(MASTERS)
    fake.answers.update({
        "/api/v1/auth/cert": PEM,
        "/apis/v1/doctors/generate-mobile-otp": {"status": "OTP sent", "txnId": "txn-m"},
        "/apis/v1/doctors/verify-mobile-otp": {"status": "verified", "txnId": "txn-m"},
        "/apis/v1/doctors/generate-verification-email": {"status": "OTP sent"},
        "/apis/v1/doctors/verify-email-otp": {"status": "verified"},
        REGISTER: {"referenceNumber": "REF9", "status": "SUBMITTED", "message": "Registered"},
    })
    for module in (hpr_login, hpid, hpr_contact):
        monkeypatch.setattr(module, "get_redis", lambda: redis)
    monkeypatch.setattr(client, "call", fake.call)
    app = FastAPI()
    app.include_router(hpr_router.router)
    caller = DbUser(id=uuid.uuid4(), keycloak_sub="sub-admin", username="admin", facility_id=uuid.uuid4(), roles=["admin"])
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub=caller.keycloak_sub, roles=["admin"])
    app.dependency_overrides[get_current_db_user] = lambda: caller
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as http:
        yield {"fake": fake, "http": http, "caller": caller}


async def _sign_in(desk, number="71-0000-0000-0002", kyc=NO_CONTACT) -> str:
    token = _jwt(hprId="asha.verma@hpr.abdm", hprIdNumber=number, ROLE="DOCTOR", exp=int(time.time()) + 900)
    await hpr_login._keep(desk["caller"].facility_id, desk["caller"].id, "asha.verma@hpr.abdm", token, kyc=kyc)
    return token


async def _verify_both(desk) -> None:
    http = desk["http"]
    assert (await http.post("/abdm/hpr/contact/mobile", json={"mobile": "9123456780"})).status_code == 200
    assert (await http.post("/abdm/hpr/contact/mobile/verify", json={"otp": "123456"})).status_code == 200
    assert (await http.post("/abdm/hpr/contact/email", json={"email": "asha.real@example.org"})).status_code == 200
    assert (await http.post("/abdm/hpr/contact/email/verify", json={"otp": "654321"})).status_code == 200


async def test_the_mobile_and_otp_travel_encrypted_as_nhas_document_gives_them(desk):
    token = await _sign_in(desk)
    await _verify_both(desk)
    sent = desk["fake"].sent("/apis/v1/doctors/generate-mobile-otp")[2]
    assert sent["hpr_token"] == token and _plain(sent["officialMobile"]) == "9123456780"
    verify = desk["fake"].sent("/apis/v1/doctors/verify-mobile-otp")[2]
    assert verify["txnId"] == "txn-m" and _plain(verify["otp"]) == "123456"
    assert desk["fake"].sent("/apis/v1/doctors/generate-verification-email")[2] == {
        "emailAddress": "asha.real@example.org", "otp_type": ""}
    email = desk["fake"].sent("/apis/v1/doctors/verify-email-otp")[2]
    assert email == {"hpr_token": token, "hpr_id": "asha.verma@hpr.abdm",
                     "officialEmail": "asha.real@example.org", "emailOtp": 654321}
    status = (await desk["http"].get("/abdm/hpr/contact")).json()
    assert status == {"mobile_verified": True, "mobile_hint": "6780", "email_verified": True,
                      "email": "asha.real@example.org"}


async def test_registration_sends_the_verified_contacts_not_the_typed_ones(desk):
    await _sign_in(desk)
    refused = await desk["http"].post("/abdm/hpr/professional", json=_form(official_mobile="9000000000"))
    assert refused.status_code == 409 and refused.json()["detail"]["message"] == "Verify the official mobile by OTP first"
    await _verify_both(desk)
    sent = await desk["http"].post("/abdm/hpr/professional",
                                   json=_form(official_mobile="9000000000", official_email="typed@example.org"))
    assert sent.status_code == 200, sent.text
    practitioner = desk["fake"].sent(REGISTER)[2]["practitioner"]
    assert practitioner["officialMobile"] == "9123456780" and practitioner["officialEmail"] == "asha.real@example.org"


async def test_a_wrong_otp_is_hprs_refusal_and_nothing_is_verified(desk):
    await _sign_in(desk)
    desk["fake"].answers["/apis/v1/doctors/verify-mobile-otp"] = AbdmRejected(
        400, {"code": "HIS-400", "details": [{"message": "Invalid OTP"}]}, "rid")
    await desk["http"].post("/abdm/hpr/contact/mobile", json={"mobile": "9123456780"})
    wrong = await desk["http"].post("/abdm/hpr/contact/mobile/verify", json={"otp": "000000"})
    assert wrong.status_code == 400 and "Invalid OTP" in wrong.text
    assert (await desk["http"].get("/abdm/hpr/contact")).json()["mobile_verified"] is False


async def test_another_professionals_verification_never_carries_over(desk):
    await _sign_in(desk, number="71-0000-0000-0002")
    await _verify_both(desk)
    await _sign_in(desk, number="71-0000-0000-0009")
    assert (await desk["http"].get("/abdm/hpr/contact")).json()["mobile_verified"] is False
    refused = await desk["http"].post("/abdm/hpr/professional", json=_form())
    assert refused.status_code == 409


async def test_a_verify_before_any_otp_is_refused(desk):
    await _sign_in(desk)
    early = await desk["http"].post("/abdm/hpr/contact/email/verify", json={"otp": "123456"})
    assert early.status_code == 409 and early.json()["detail"]["message"] == "Send the email OTP first"

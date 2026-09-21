"""HTTP contract of the M1 identity routes for the desk's negative cases.

Fully mocked gateway and Redis; SQLite patient rows. Asserts the wire shape a
reception client depends on: a refused OTP is a correctable 400 that keeps the
session (workbook VRFY_ABHA_304/402), an early resend is a 429 with Retry-After,
a resend for the wrong patient is the same 404 as a missing session, and an
Aadhaar-keyed login request reaches the gateway with the aadhaar-verify scope.
"""
import json
import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.common.db import get_db
from app.integrations.abdm.client import AbdmRejected, AbdmResponse
from app.integrations.abdm.identity import crypto, otp_session, service
from app.integrations.abdm.identity.router import router as identity_router
from tests.test_suite_8_immunization_blood_forms import _setup_suite_8_fixture

pytestmark = pytest.mark.asyncio

AADHAAR = "999988887777"
CONSENT = {
    "granted": True,
    "code": "abha-enrollment",
    "version": "1.4",
    "language": "en",
}


class _Redis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


class _Gateway:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def request(self, method, path, *, json=None, **kw):
        self.calls.append((path, json))
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return AbdmResponse(200, nxt, "req-id")


@pytest_asyncio.fixture
async def desk(db, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    class _S:
        abdm_public_key_pem = pem
        abdm_abha_base_url = "https://abha.test/abha/api"
        abdm_path_enrol_request_otp = "/v3/enrollment/request/otp"
        abdm_path_enrol_by_aadhaar = "/v3/enrollment/enrol/byAadhaar"
        abdm_path_enrol_auth_by_abdm = "/v3/enrollment/auth/byAbdm"
        abdm_path_enrol_suggestion = "/v3/enrollment/enrol/suggestion"
        abdm_path_enrol_abha_address = "/v3/enrollment/enrol/abha-address"
        abdm_path_profile_account = "/v3/profile/account"
        abdm_path_profile_abha_card = "/v3/profile/account/abha-card"
        abdm_path_login_request_otp = "/v3/profile/login/request/otp"
        abdm_path_login_verify = "/v3/profile/login/verify"

    monkeypatch.setattr(crypto, "get_settings", lambda: _S())
    monkeypatch.setattr(service, "get_settings", lambda: _S())
    redis = _Redis()
    monkeypatch.setattr(otp_session, "get_redis", lambda: redis)
    gateway = _Gateway([])
    monkeypatch.setattr(service, "get_abdm_client", lambda: gateway)

    facility, staff, patient, _other = await _setup_suite_8_fixture(db)
    await db.commit()
    caller = DbUser(id=staff.id, keycloak_sub=staff.keycloak_sub, username=staff.username,
                    facility_id=facility.id, roles=["receptionist"])
    app = FastAPI()
    app.include_router(identity_router)

    async def session():
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub=caller.keycloak_sub, roles=caller.roles)
    app.dependency_overrides[get_current_db_user] = lambda: caller
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test",
                                 headers={"Idempotency-Key": str(uuid.uuid4())}) as client:
        yield {"client": client, "gateway": gateway, "redis": redis, "patient": patient, "staff": staff}


async def test_a_refused_otp_is_a_correctable_400_and_keeps_the_session(desk):
    desk["gateway"].responses = [{"txnId": "abdm-txn-1"}, AbdmRejected(400, {"code": "ABDM-1"}, "rid")]
    requested = await desk["client"].post("/abdm/abha/login/request-otp", json={
        "patient_id": str(desk["patient"].id), "aadhaar": AADHAAR})
    assert requested.status_code == 200, requested.text
    assert requested.json()["resends_remaining"] == otp_session.MAX_RESENDS
    assert desk["gateway"].calls[0][1]["scope"] == ["abha-login", "aadhaar-verify"]
    session_id = requested.json()["session_id"]

    verify = await desk["client"].post("/abdm/abha/login/verify-otp", json={"session_id": session_id, "otp": "000000"})
    assert verify.status_code == 400, verify.text
    assert verify.json()["detail"]["code"] == "otp_rejected"
    assert f"abdm:otp:{session_id}" in desk["redis"].store, "a wrong OTP must not end the exchange"
    assert AADHAAR not in verify.text and AADHAAR not in json.dumps(list(desk["redis"].store.values()))


async def test_login_request_refuses_zero_or_two_identifiers(desk):
    for body in ({"patient_id": str(desk["patient"].id)},
                 {"patient_id": str(desk["patient"].id), "aadhaar": AADHAAR, "abha_number": "91111122223333"}):
        response = await desk["client"].post("/abdm/abha/login/request-otp", json=body)
        assert response.status_code == 422, response.text
    assert desk["gateway"].calls == []


async def test_early_resend_is_429_with_retry_after_and_wrong_patient_is_404(desk):
    desk["gateway"].responses = [{"txnId": "abdm-txn-1"}, {"txnId": "abdm-txn-2"}]
    requested = await desk["client"].post("/abdm/abha/enrol/aadhaar/request-otp", json={
        "patient_id": str(desk["patient"].id), "aadhaar": AADHAAR, "consent": CONSENT})
    assert requested.status_code == 200, requested.text
    session_id = requested.json()["session_id"]
    body = {"session_id": session_id, "patient_id": str(desk["patient"].id), "aadhaar": AADHAAR}

    too_soon = await desk["client"].post("/abdm/abha/enrol/aadhaar/resend-otp", json=body)
    assert too_soon.status_code == 429, too_soon.text
    assert too_soon.json()["detail"]["code"] == "otp_resend_too_soon"
    assert int(too_soon.headers["retry-after"]) >= 1
    assert len(desk["gateway"].calls) == 1

    wrong_patient = await desk["client"].post("/abdm/abha/enrol/aadhaar/resend-otp",
                                              json={**body, "patient_id": str(uuid.uuid4())})
    assert wrong_patient.status_code == 404
    assert wrong_patient.json()["detail"]["code"] in {"otp_session_not_found", "patient_not_found"}

    stored = json.loads(desk["redis"].store[f"abdm:otp:{session_id}"])
    stored["created_at"] = "2026-09-20T00:00:00+00:00"
    desk["redis"].store[f"abdm:otp:{session_id}"] = json.dumps(stored)
    resent = await desk["client"].post("/abdm/abha/enrol/aadhaar/resend-otp", json=body)
    assert resent.status_code == 200, resent.text
    assert resent.json()["session_id"] != session_id
    assert resent.json()["resends_remaining"] == otp_session.MAX_RESENDS - 1
    assert f"abdm:otp:{session_id}" not in desk["redis"].store
    assert len(desk["gateway"].calls) == 2 and desk["gateway"].calls[1][1]["txnId"] == ""


async def test_declined_enrolment_consent_is_400_and_does_not_call_abdm(desk):
    response = await desk["client"].post("/abdm/abha/enrol/aadhaar/request-otp", json={
        "patient_id": str(desk["patient"].id),
        "aadhaar": AADHAAR,
        "consent": {**CONSENT, "granted": False},
    })
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "enrolment_consent_refused"
    assert desk["gateway"].calls == []
    assert AADHAAR not in response.text

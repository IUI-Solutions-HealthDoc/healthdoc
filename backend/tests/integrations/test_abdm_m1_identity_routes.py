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
from fastapi import FastAPI, HTTPException
from sqlalchemy import select

from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.common.db import get_db
from app.integrations.abdm.client import AbdmRejected, AbdmResponse, AbdmUnavailable
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
        abdm_path_phr_login_request_otp = "/v3/phr/web/login/abha/request/otp"
        abdm_path_phr_login_verify = "/v3/phr/web/login/abha/verify"
        abdm_path_phr_profile = "/v3/phr/web/login/profile/abha-profile"
        abdm_path_phr_card = "/v3/phr/web/login/profile/abha/phr-card"

    monkeypatch.setattr(crypto, "get_settings", lambda: _S())
    monkeypatch.setattr(service, "get_settings", lambda: _S())
    redis = _Redis()
    monkeypatch.setattr(otp_session, "get_redis", lambda: redis)
    gateway = _Gateway([])
    monkeypatch.setattr(service, "get_abdm_client", lambda: gateway)

    facility, staff, patient, _other = await _setup_suite_8_fixture(db)
    facility.ownership = "government"
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
        yield {"client": client, "gateway": gateway, "redis": redis, "patient": patient, "staff": staff,
               "other": _other, "facility": facility, "db": db}


async def consent_for(desk, **ticks):
    """What the desk sends after showing NHA's declaration: its own defaults,
    both confirmations ticked, then any override."""
    shown = await desk["client"].get(
        "/abdm/abha/enrol/consent", params={"patient_id": str(desk["patient"].id)})
    assert shown.status_code == 200, shown.text
    declaration = shown.json()["declaration"]
    statements = {row["id"]: row["ticked"] for row in declaration["statements"]}
    statements.update({"health_worker": True, "beneficiary": True, **ticks})
    return {**CONSENT, "statements": statements, "declaration_sha256": declaration["sha256"]}


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



async def test_an_otp_abdm_reports_as_failed_is_a_correctable_400(desk):
    # ABDM answers a wrong OTP with HTTP 200 and authResult "failed" (live,
    # 7 Oct 2026); a 502 "temporarily unavailable" sent the desk to wait.
    desk["gateway"].responses = [{"txnId": "abdm-txn-1"}, {"authResult": "failed", "message": "x"}]
    requested = await desk["client"].post("/abdm/abha/login/request-otp", json={
        "patient_id": str(desk["patient"].id), "aadhaar": AADHAAR})
    assert requested.status_code == 200, requested.text
    verify = await desk["client"].post("/abdm/abha/login/verify-otp",
                                       json={"session_id": requested.json()["session_id"], "otp": "000000"})
    assert verify.status_code == 400, verify.text
    assert verify.json()["detail"]["code"] == "abdm_auth_failed"


@pytest.mark.parametrize("refusal", [
    AbdmRejected(422, {"error": {"code": "ABDM-1204", "message": "Invalid"}}, "rid"),
    AbdmRejected(422, {"error": {"code": "ABDM-1204: ", "message": "Invalid"}}, "rid"),
    AbdmRejected(400, {"loginId": "Invalid LoginId", "timestamp": "t"}, "rid"),
], ids=["code", "code-separator", "loginId-field"])
@pytest.mark.parametrize("route", ["enrol", "login"])
async def test_an_aadhaar_abdm_refuses_is_a_correctable_400(desk, route, refusal):
    # CRT_ABHA_104: ABDM refuses an invalid Aadhaar in both shapes (live, 7 Oct 2026).
    desk["gateway"].responses = [refusal]
    if route == "enrol":
        response = await desk["client"].post("/abdm/abha/enrol/aadhaar/request-otp", json={
            "patient_id": str(desk["patient"].id), "aadhaar": AADHAAR, "consent": await consent_for(desk)})
    else:
        response = await desk["client"].post("/abdm/abha/login/request-otp", json={
            "patient_id": str(desk["patient"].id), "aadhaar": AADHAAR})
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "aadhaar_invalid"
    assert AADHAAR not in response.text


async def test_a_refused_abha_number_is_not_called_an_invalid_aadhaar(desk):
    desk["gateway"].responses = [AbdmRejected(400, {"loginId": "Invalid LoginId"}, "rid")]
    response = await desk["client"].post("/abdm/abha/login/request-otp", json={
        "patient_id": str(desk["patient"].id), "abha_number": "91111122223333"})
    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "abdm_rejected"


@pytest.mark.parametrize(("body", "expected"), [
    ({"mobile": "9876543210"}, "abha_not_found_for_mobile"),
    ({"aadhaar": AADHAAR}, "abha_not_found_for_aadhaar"),
])
async def test_no_abha_behind_the_identifier_is_a_not_found_not_a_decline(desk, monkeypatch, body, expected):
    # VRFY_ABHA_302/403: ABDM refuses the OTP request with 404 ABDM-1115 and
    # sends no OTP (live, 7 Oct 2026).
    from app.common import captcha
    async def _ok(*_args):
        return True
    monkeypatch.setattr(captcha, "check", _ok)
    desk["gateway"].responses = [AbdmRejected(404, {"error": {"code": "ABDM-1115", "message": "x"}}, "rid")]
    response = await desk["client"].post("/abdm/abha/login/request-otp", json={
        "patient_id": str(desk["patient"].id), "captcha_id": "c", "captcha_answer": "a", **body})
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == expected
    assert "9876543210" not in response.text and AADHAAR not in response.text


async def test_an_enrolment_404_is_not_reported_as_no_abha(desk):
    desk["gateway"].responses = [AbdmRejected(404, {"error": {"code": "ABDM-1115"}}, "rid")]
    response = await desk["client"].post("/abdm/abha/enrol/aadhaar/request-otp", json={
        "patient_id": str(desk["patient"].id), "aadhaar": AADHAAR, "consent": await consent_for(desk)})
    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "abdm_rejected"


async def test_any_other_otp_request_refusal_stays_a_gateway_decline(desk):
    desk["gateway"].responses = [AbdmRejected(422, {"error": {"code": "ABDM-1999"}}, "rid")]
    response = await desk["client"].post("/abdm/abha/enrol/aadhaar/request-otp", json={
        "patient_id": str(desk["patient"].id), "aadhaar": AADHAAR, "consent": await consent_for(desk)})
    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "abdm_rejected"

async def test_login_request_refuses_zero_or_two_identifiers(desk):
    for body in ({"patient_id": str(desk["patient"].id)},
                 {"patient_id": str(desk["patient"].id), "aadhaar": AADHAAR, "abha_number": "91111122223333"}):
        response = await desk["client"].post("/abdm/abha/login/request-otp", json=body)
        assert response.status_code == 422, response.text
    assert desk["gateway"].calls == []


async def test_early_resend_is_429_with_retry_after_and_wrong_patient_is_404(desk):
    desk["gateway"].responses = [{"txnId": "abdm-txn-1"}, {"txnId": "abdm-txn-2"}]
    requested = await desk["client"].post("/abdm/abha/enrol/aadhaar/request-otp", json={
        "patient_id": str(desk["patient"].id), "aadhaar": AADHAAR, "consent": await consent_for(desk)})
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
        "consent": {**(await consent_for(desk)), "granted": False},
    })
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "enrolment_consent_refused"
    assert desk["gateway"].calls == []
    assert AADHAAR not in response.text


async def _enrolment_session(desk) -> str:
    desk["gateway"].responses = [{"txnId": "abdm-txn-1"}]
    requested = await desk["client"].post("/abdm/abha/enrol/aadhaar/request-otp", json={
        "patient_id": str(desk["patient"].id), "aadhaar": AADHAAR, "consent": await consent_for(desk)})
    assert requested.status_code == 200, requested.text
    return requested.json()["session_id"]


async def test_enrolment_verify_without_a_mobile_is_refused_before_the_otp_is_spent(desk):
    session_id = await _enrolment_session(desk)
    response = await desk["client"].post("/abdm/abha/enrol/aadhaar/verify-otp",
                                         json={"session_id": session_id, "otp": "123456"})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "abha_mobile_required"
    assert len(desk["gateway"].calls) == 1, "the OTP must not reach ABDM without the mobile"
    assert f"abdm:otp:{session_id}" in desk["redis"].store


async def test_a_refused_enrolment_mobile_is_not_reported_as_a_wrong_otp(desk):
    session_id = await _enrolment_session(desk)
    # byAadhaar's refusal names the mobile field (live, 6 Oct 2026).
    desk["gateway"].responses = [AbdmRejected(400, {"mobile": "Invalid mobile", "timestamp": "t"}, "rid")]
    response = await desk["client"].post("/abdm/abha/enrol/aadhaar/verify-otp",
                                         json={"session_id": session_id, "otp": "123456", "mobile": "9876543210"})
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "abha_mobile_rejected"
    assert f"abdm:otp:{session_id}" in desk["redis"].store
    assert "9876543210" not in response.text


@pytest.mark.parametrize(
    ("codes", "expected"),
    [(("ABDM-1206",), "aadhaar_service_unavailable"),
     (("ABDM-1206: ",), "aadhaar_service_unavailable"),
     ((), "abdm_unavailable")],
)
async def test_an_abdm_outage_names_the_service_that_is_down(desk, codes, expected):
    desk["gateway"].responses = [
        AbdmUnavailable("ABDM request unavailable", status_code=504, stage="request", error_codes=codes)]
    response = await desk["client"].post("/abdm/abha/enrol/aadhaar/request-otp", json={
        "patient_id": str(desk["patient"].id), "aadhaar": AADHAAR, "consent": await consent_for(desk)})
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == expected
    assert AADHAAR not in response.text


LINKED_ABHA = "91111122223333"


async def test_unlink_needs_a_reason_and_is_audited_without_the_number(desk, db):
    from app.audit.models import AuditLog
    from app.patients.models import Patient

    patient = desk["patient"]
    patient.abha_number = LINKED_ABHA
    patient.identity_status = "verified"
    await db.commit()
    url = f"/abdm/abha/patients/{patient.id}/abha"

    for body in (None, {"reason": "short"}, {"reason": "         x          "}):
        refused = await desk["client"].request("DELETE", url, json=body)
        assert refused.status_code == 422, refused.text
    await db.refresh(patient)
    assert patient.abha_number == LINKED_ABHA

    unlinked = await desk["client"].request(
        "DELETE", url, json={"reason": "Linked to the wrong chart at the desk"}
    )
    assert unlinked.status_code == 200, unlinked.text
    stored = (await db.execute(select(Patient).where(Patient.id == patient.id))).scalar_one()
    await db.refresh(stored)
    assert stored.abha_number is None
    assert stored.identity_status == "identity_unverified"

    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.resource_type == "patients", AuditLog.resource_id == patient.id
            )
        )
    ).scalars().all()
    assert len(audit) == 1
    row = audit[0]
    assert row.reason == "ABHA unlinked: Linked to the wrong chart at the desk"
    assert row.old_value == {"abha_linked": True, "identity_status": "verified"}
    assert row.new_value == {"abha_linked": False, "identity_status": "identity_unverified"}
    assert str(row.user_id) == str(desk["staff"].id)
    assert LINKED_ABHA not in json.dumps([row.old_value, row.new_value, row.reason])


async def _link_through_otp(monkeypatch, db, caller_patient, staff):
    from app.auth.deps import DbUser
    from app.integrations.abdm.identity import router as identity_module

    class _Session:
        patient_id = str(caller_patient.id)

    async def _bound(*_args, **_kwargs):
        return _Session()

    monkeypatch.setattr(identity_module, "_bound_otp_session", _bound)
    caller = DbUser(id=staff.id, keycloak_sub=staff.keycloak_sub, username=staff.username,
                    facility_id=caller_patient.facility_id, roles=["receptionist"])
    issued = service.AbhaIssued(
        abha_number=LINKED_ABHA, abha_address=None, linking_token=None,
        name=None, gender=None, date_of_birth=None,
    )
    return await identity_module._persist_verified_identity(
        db=db, current_db_user=caller, session_id="s", purpose=otp_session.OtpPurpose.LOGIN_BY_ABHA,
        issued=issued, consume_session=False,
    )


async def test_an_abha_held_at_another_facility_links_here_too(desk, db, monkeypatch):
    """Each facility is its own HIP (0095): one person, a linked chart at each."""
    from app.patients.models import Patient
    from app.users.models import Facility

    other_facility = Facility(id=uuid.uuid4(), name="Elsewhere", code=f"ELS{uuid.uuid4().hex[:4].upper()}",
                              state_code="MH")
    db.add(other_facility)
    await db.flush()
    elsewhere = Patient(
        id=uuid.uuid4(), facility_id=other_facility.id, uhid=f"UHID-ELS-{uuid.uuid4().hex[:6]}",
        full_name="Someone Else", sex="female", age_years=40, status="active",
        identity_path="demographics_only", created_by=desk["staff"].id, abha_number=LINKED_ABHA,
    )
    db.add(elsewhere)
    await db.commit()

    await _link_through_otp(monkeypatch, db, desk["patient"], desk["staff"])
    await db.refresh(desk["patient"])
    await db.refresh(elsewhere)
    assert desk["patient"].abha_number == LINKED_ABHA
    assert elsewhere.abha_number == LINKED_ABHA, "the other facility's chart is untouched"


async def test_an_abha_held_at_this_facility_still_says_duplicate(desk, db, monkeypatch):
    from app.patients.models import Patient

    db.add(Patient(
        id=uuid.uuid4(), facility_id=desk["patient"].facility_id, uhid=f"UHID-DUP-{uuid.uuid4().hex[:6]}",
        full_name="First Chart", sex="female", age_years=40, status="active",
        identity_path="demographics_only", created_by=desk["staff"].id, abha_number=LINKED_ABHA,
    ))
    await db.commit()

    with pytest.raises(HTTPException) as refused:
        await _link_through_otp(monkeypatch, db, desk["patient"], desk["staff"])
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "duplicate_abha"


# ------------------------------------------ ABHA-address (PHR) login through the desk
_PHR_VERIFIED = {
    "authResult": "success",
    "users": [{"abhaAddress": "singh128@sbx", "fullName": "Deepak Kumar Singh",
               "abhaNumber": "91-6167-8028-XXXX", "status": "ACTIVE", "kycStatus": "VERIFIED"}],
    "tokens": {"token": "phr-x-token", "refreshToken": "phr-refresh"},
}


async def _address_login(desk):
    desk["gateway"].responses = [{"txnId": "phr-txn"}, _PHR_VERIFIED]
    requested = await desk["client"].post("/abdm/abha/login/request-otp", json={
        "patient_id": str(desk["patient"].id), "abha_address": "singh128@sbx"})
    assert requested.status_code == 200, requested.text
    return await desk["client"].post("/abdm/abha/login/verify-otp", json={
        "session_id": requested.json()["session_id"], "otp": "123456"})


async def test_abha_address_login_binds_the_address_and_never_a_placeholder_number(desk, db):
    from app.common.security import decrypt_pii

    patient = desk["patient"]
    patient.abha_number, patient.abha_address = None, None
    await db.commit()

    verified = await _address_login(desk)

    assert verified.status_code == 200, verified.text
    assert desk["gateway"].calls[0][0].endswith("/v3/phr/web/login/abha/request/otp")
    assert desk["gateway"].calls[1][0].endswith("/v3/phr/web/login/abha/verify")
    assert verified.json()["abha_address"] == "singh128@sbx"
    assert verified.json()["abha_number"] == ""
    assert "phr-x-token" not in verified.text
    await db.refresh(patient)
    assert patient.abha_number is None, "an empty or masked number must not be stored (the column is unique)"
    assert patient.abha_address == "singh128@sbx"
    assert patient.identity_status == "verified"
    assert patient.abha_profile_token_kind == "phr"
    assert decrypt_pii(patient.abha_profile_token_encrypted) == "phr-x-token"


async def test_a_second_chart_cannot_take_a_linked_abha_address(desk, db):
    desk["patient"].abha_number, desk["patient"].abha_address = None, None
    desk["other"].abha_address = "singh128@sbx"
    await db.commit()

    verified = await _address_login(desk)

    assert verified.status_code == 409, verified.text
    assert verified.json()["detail"]["code"] == "duplicate_abha_address"


async def test_an_abha_address_held_at_another_facility_links_here_too(desk, db):
    from app.patients.models import Patient
    from app.users.models import Facility

    desk["patient"].abha_number, desk["patient"].abha_address = None, None
    other_facility = Facility(id=uuid.uuid4(), name="Elsewhere", code=f"ELS{uuid.uuid4().hex[:4].upper()}",
                              state_code="MH")
    db.add(other_facility)
    await db.flush()
    db.add(Patient(
        id=uuid.uuid4(), facility_id=other_facility.id, uhid=f"UHID-ELS-{uuid.uuid4().hex[:6]}",
        full_name="Someone Else", sex="female", age_years=40, status="active",
        identity_path="demographics_only", created_by=desk["staff"].id, abha_address="singh128@sbx",
    ))
    await db.commit()

    verified = await _address_login(desk)

    assert verified.status_code == 200, verified.text
    await db.refresh(desk["patient"])
    assert desk["patient"].abha_address == "singh128@sbx"


async def test_phr_card_is_fetched_from_the_phr_endpoint_and_unlink_resets_the_kind(desk, db):
    patient = desk["patient"]
    patient.abha_number, patient.abha_address = None, None
    await db.commit()
    assert (await _address_login(desk)).status_code == 200

    desk["gateway"].responses = [b"\x89card"]
    card = await desk["client"].get(f"/abdm/abha/patients/{patient.id}/abha-card")
    assert card.status_code == 200, card.text
    assert desk["gateway"].calls[-1][0].endswith("/v3/phr/web/login/profile/abha/phr-card")

    unlinked = await desk["client"].request(
        "DELETE",
        f"/abdm/abha/patients/{patient.id}/abha",
        json={"reason": "Address linked to the wrong chart"},
    )
    assert unlinked.status_code == 200, unlinked.text
    await db.refresh(patient)
    assert patient.abha_address is None and patient.abha_profile_token_encrypted is None
    assert patient.abha_profile_token_kind == "abha"

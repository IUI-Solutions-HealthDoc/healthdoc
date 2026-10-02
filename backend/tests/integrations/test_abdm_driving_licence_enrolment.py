"""M1 CRT_ABHA_401-411: ABHA enrolment with a driving licence.

Shape from NHA's M1 Postman, "ABHA Enrolment via DL": request/otp and
auth/byAbdm with scope [abha-enrol, mobile-verify, dl-flow], then
enrol/byDocument. ABDM returns an enrolment number in PROVISIONAL state; the
ABHA is issued only after a facility verifies the licence, so nothing is bound
to the chart. Consent is NHA's declaration with the "document other than
Aadhaar" statement ticked and the Aadhaar statement unticked.
"""

import base64
import json

import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.integrations.abdm.client import AbdmRejected
from app.integrations.abdm.identity import enrolment_consent as ec
from app.integrations.abdm.identity import service
from app.patients.models import Patient
from tests.integrations.test_abdm_demographic_enrolment import lgd_file  # noqa: F401
from tests.integrations.test_abdm_m1_identity_routes import CONSENT, desk  # noqa: F401

pytestmark = pytest.mark.asyncio

MOBILE = "9876543210"
JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"synthetic licence side" * 4).decode()
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"synthetic back side" * 4).decode()
ENROLLED = {
    "message": "Account created successfully",
    "enrolProfile": {
        "enrolmentNumber": "91-6483-6362-1216",
        "enrolmentState": "PROVISIONAL",
        "phrAddress": ["91648363621216@sbx"],
    },
    "isNew": True,
}


@pytest.fixture
def licence(desk, lgd_file, monkeypatch):  # noqa: F811
    base = type(service.get_settings())

    class _S(base):
        abdm_path_enrol_by_document = "/v3/enrollment/enrol/byDocument"

    monkeypatch.setattr(service, "get_settings", lambda: _S())
    # A refused request rolls the session back and expires loaded rows; keep
    # the ids as plain strings so later requests do not reload them.
    desk["patient_id"], desk["other_id"] = str(desk["patient"].id), str(desk["other"].id)
    return desk


async def _consent(desk, method="document", **ticks):  # noqa: F811
    shown = await desk["client"].get(
        "/abdm/abha/enrol/consent",
        params={"patient_id": desk["patient_id"], "method": method},
    )
    assert shown.status_code == 200, shown.text
    declaration = shown.json()["declaration"]
    statements = {row["id"]: row["ticked"] for row in declaration["statements"]}
    statements.update({"health_worker": True, "beneficiary": True, **ticks})
    return {**CONSENT, "statements": statements, "declaration_sha256": declaration["sha256"]}


async def _request(desk, consent=None):  # noqa: F811
    return await desk["client"].post("/abdm/abha/enrol/driving-licence/request-otp", json={
        "patient_id": desk["patient_id"], "mobile": MOBILE,
        "consent": consent or await _consent(desk),
    })


async def _verified_session(desk):  # noqa: F811
    desk["gateway"].responses = [{"txnId": "txn-otp", "message": "OTP sent to ******3210"},
                                 {"txnId": "txn-verified", "authResult": "success"}]
    requested = await _request(desk)
    assert requested.status_code == 200, requested.text
    session_id = requested.json()["session_id"]
    verified = await desk["client"].post("/abdm/abha/enrol/driving-licence/verify-otp", json={
        "session_id": session_id, "patient_id": desk["patient_id"], "otp": "123456"})
    assert verified.status_code == 204, verified.text
    return session_id


def _details(desk, session_id, **change):  # noqa: F811
    body = {
        "session_id": session_id, "patient_id": desk["patient_id"],
        "licence_number": "MH12 20110012345", "first_name": "Aarav", "middle_name": "",
        "last_name": "Sharma", "date_of_birth": "1990-05-17", "gender": "M",
        "address": "12 Synthetic Lane", "pincode": "415001", "state_code": "27",
        "district_code": "494", "front_photo": f"data:image/jpeg;base64,{JPEG}",
        "back_photo": PNG, "operator_verified": True,
    }
    body.update(change)
    return body


# ------------------------------------------------------------ consent


def test_a_document_enrolment_flips_only_the_first_two_statements():
    aadhaar = ec.declaration(ownership="government", health_worker="N", beneficiary="P")
    document = ec.declaration(
        ownership="government", health_worker="N", beneficiary="P", method="document"
    )
    flips = {"aadhaar_sharing": (False, False), "other_document": (True, True)}
    for before, after in zip(aadhaar["statements"], document["statements"], strict=True):
        assert after["text"] == before["text"]
        expected = flips.get(before["id"], (before["ticked"], before["required"]))
        assert (after["ticked"], after["required"]) == expected
    assert document["sha256"] != aadhaar["sha256"]
    assert document["method"] == "document"
    choices = {s["id"]: bool(s["ticked"]) or s["required"] is True for s in document["statements"]}
    with pytest.raises(ec.DeclarationRefused) as refused:
        ec.accept_declaration(document, {**choices, "aadhaar_sharing": True})
    assert refused.value.code == "enrolment_aadhaar_selected"
    with pytest.raises(ec.DeclarationRefused) as refused:
        ec.accept_declaration(document, {**choices, "other_document": False})
    assert refused.value.code == "enrolment_consent_refused"


async def test_an_aadhaar_consent_cannot_start_a_licence_enrolment(licence):
    aadhaar_consent = await _consent(licence, method="aadhaar")
    response = await _request(licence, aadhaar_consent)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "enrolment_declaration_changed"
    assert licence["gateway"].calls == []


# ------------------------------------------------------- happy path


async def test_the_licence_enrolment_follows_nhas_dl_flow_and_binds_nothing(licence, db):
    session_id = await _verified_session(licence)
    (otp_path, otp_body), (verify_path, verify_body) = licence["gateway"].calls
    assert otp_path.endswith("/v3/enrollment/request/otp")
    assert otp_body["scope"] == ["abha-enrol", "mobile-verify", "dl-flow"]
    assert otp_body["loginHint"] == "mobile" and otp_body["otpSystem"] == "abdm"
    assert otp_body["loginId"] != MOBILE and "txnId" not in otp_body
    assert verify_path.endswith("/v3/enrollment/auth/byAbdm")
    assert verify_body["scope"] == ["abha-enrol", "mobile-verify", "dl-flow"]
    assert verify_body["authData"]["otp"]["txnId"] == "txn-otp"

    licence["gateway"].responses = [ENROLLED]
    enrolled = await licence["client"].post(
        "/abdm/abha/enrol/driving-licence", json=_details(licence, session_id))
    assert enrolled.status_code == 200, enrolled.text
    assert enrolled.json() == {
        "enrolment_number": "91-6483-6362-1216", "enrolment_state": "PROVISIONAL",
        "abha_address": "91648363621216@sbx", "is_new": True, "linked": False,
    }
    path, body = licence["gateway"].calls[-1]
    assert path.endswith("/v3/enrollment/enrol/byDocument")
    assert body == {
        "txnId": "txn-verified", "documentType": "DRIVING_LICENCE",
        "documentId": "MH12 20110012345", "firstName": "Aarav", "middleName": "",
        "lastName": "Sharma", "dob": "17-05-1990", "gender": "M",
        "frontSidePhoto": JPEG, "backSidePhoto": PNG, "address": "12 Synthetic Lane",
        "state": "MAHARASHTRA", "district": "SATARA", "pinCode": "415001",
        "consent": {"code": "abha-enrollment", "version": "1.4"},
    }

    patient = await db.get(Patient, licence["patient"].id, populate_existing=True)
    assert patient.abha_number is None and patient.abha_address is None
    rows = (await db.execute(select(AuditLog).where(
        AuditLog.patient_id == patient.id,
        AuditLog.resource_type.in_(("abha_enrolment_consent", "abha_document_enrolment")),
    ))).scalars().all()
    consent_row = next(r for r in rows if r.resource_type == "abha_enrolment_consent")
    assert consent_row.new_value["method"] == "driving_licence"
    assert consent_row.new_value["statements"]["other_document"] is True
    assert consent_row.new_value["statements"]["aadhaar_sharing"] is False
    enrolment_row = next(r for r in rows if r.resource_type == "abha_document_enrolment")
    assert enrolment_row.new_value["enrolment_number"] == "91-6483-6362-1216"
    assert enrolment_row.new_value["operator_verified"] is True
    stored = json.dumps([row.new_value for row in rows]) + json.dumps(
        list(licence["redis"].store.values()))
    assert MOBILE not in stored and JPEG not in stored
    assert f"abdm:otp:{session_id}" not in licence["redis"].store


# ------------------------------------------------------- refusals


async def test_the_licence_cannot_be_sent_before_the_mobile_is_verified(licence):
    licence["gateway"].responses = [{"txnId": "txn-otp"}]
    requested = await _request(licence)
    session_id = requested.json()["session_id"]
    response = await licence["client"].post(
        "/abdm/abha/enrol/driving-licence", json=_details(licence, session_id))
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "enrolment_stage_invalid"
    assert len(licence["gateway"].calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"operator_verified": False},
        {"front_photo": base64.b64encode(b"%PDF-1.7 not an image").decode()},
        {"back_photo": "not base64!"},
        {"front_photo": base64.b64encode(b"\xff\xd8\xff" + b"0" * (2 * 1024 * 1024)).decode()},
        {"licence_number": "MH-12--2011"},
        {"state_code": "27", "district_code": "77"},
    ],
)
async def test_an_unchecked_or_malformed_licence_is_refused_before_abdm(licence, change):
    session_id = await _verified_session(licence)
    response = await licence["client"].post(
        "/abdm/abha/enrol/driving-licence", json=_details(licence, session_id, **change))
    assert response.status_code in (400, 422), response.text
    assert len(licence["gateway"].calls) == 2, "only the two OTP legs reached ABDM"


async def test_details_abdm_cannot_match_are_correctable_and_keep_the_session(licence):
    session_id = await _verified_session(licence)
    licence["gateway"].responses = [AbdmRejected(422, {"error": {"code": "ABDM-1203"}}, "rid"),
                                    ENROLLED]
    refused = await licence["client"].post(
        "/abdm/abha/enrol/driving-licence", json=_details(licence, session_id))
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"]["code"] == "abha_licence_rejected"
    corrected = await licence["client"].post(
        "/abdm/abha/enrol/driving-licence",
        json=_details(licence, session_id, last_name="Sharma Kumar"))
    assert corrected.status_code == 200, corrected.text


async def test_another_patients_session_is_not_found(licence):
    session_id = await _verified_session(licence)
    body = _details(licence, session_id, patient_id=licence["other_id"])
    response = await licence["client"].post("/abdm/abha/enrol/driving-licence", json=body)
    assert response.status_code == 404
    assert len(licence["gateway"].calls) == 2


async def test_a_resend_uses_a_fresh_transaction_inside_the_limits(licence, monkeypatch):
    from app.integrations.abdm.identity import otp_session

    monkeypatch.setattr(otp_session, "RESEND_COOLDOWN_SECONDS", 0)
    licence["gateway"].responses = [{"txnId": "txn-1"}, {"txnId": "txn-2"}]
    requested = await _request(licence)
    session_id = requested.json()["session_id"]
    again = await licence["client"].post("/abdm/abha/enrol/driving-licence/resend-otp", json={
        "session_id": session_id, "patient_id": licence["patient_id"], "mobile": MOBILE})
    assert again.status_code == 200, again.text
    assert again.json()["resends_remaining"] == otp_session.MAX_RESENDS - 1
    stored = json.loads(licence["redis"].store[f"abdm:otp:{session_id}"])
    assert stored["abdm_txn_id"] == "txn-2"

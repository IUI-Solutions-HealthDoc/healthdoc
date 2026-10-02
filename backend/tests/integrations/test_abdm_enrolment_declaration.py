"""M1 CRT_ABHA_102: NHA's published ABHA consent, shown and recorded as published.

Sandbox docs, Milestone 1 > Consent Language: private entities remove the word
"government"; the second statement stays unticked for Aadhaar creation; the
beneficiary's name is the patient's; the health worker is the signed-in user.
"""

import uuid

import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.integrations.abdm.identity import enrolment_consent as ec
from tests.integrations.test_abdm_m1_identity_routes import AADHAAR, consent_for, desk  # noqa: F401

pytestmark = pytest.mark.asyncio

PUBLISHED_GOVERNMENT = [
    "I am voluntarily sharing my Aadhaar Number / Virtual ID issued by the Unique Identification "
    "Authority of India (“UIDAI”), and my demographic information for the purpose of creating an "
    "Ayushman Bharat Health Account number (“ABHA number”) and Ayushman Bharat Health Account "
    "address (“ABHA Address”). I authorize NHA to use my Aadhaar number / Virtual ID for performing "
    "Aadhaar based authentication with UIDAI as per the provisions of the Aadhaar (Targeted "
    "Delivery of Financial and other Subsidies, Benefits and Services) Act, 2016 for the aforesaid "
    "purpose. I understand that UIDAI will share my e-KYC details, or response of “Yes” with NHA "
    "upon successful authentication.",
    "I intend to create Ayushman Bharat Health Account Number (“ABHA number”) and Ayushman Bharat "
    "Health Account address (“ABHA Address”) using document other than Aadhaar.",
    "I consent to usage of my ABHA address and ABHA number for linking of my legacy (past) "
    "government health records and those which will be generated during this encounter.",
    "I authorize the sharing of all my health records with healthcare provider(s) for the purpose "
    "of providing healthcare services to me during this encounter.",
    "I consent to the anonymization and subsequent use of my government health records for public "
    "health purposes.",
    "I, Nurse Shweta, confirm that I have duly informed and explained the beneficiary of the "
    "contents of consent for aforementioned purposes.",
    "I, Aarav Sharma, have been explained about the consent as stated above and hereby provide my "
    "consent for the aforementioned purposes.",
]


def _shown(ownership="government"):
    return ec.declaration(ownership=ownership, health_worker="Nurse Shweta", beneficiary="Aarav Sharma")


def test_government_text_is_nhas_published_wording_in_order_with_its_ticks():
    shown = _shown()
    assert shown["intro"] == "I hereby declare that:"
    assert [s["text"] for s in shown["statements"]] == PUBLISHED_GOVERNMENT
    assert [s["ticked"] for s in shown["statements"]] == [True, False, True, True, True, False, False]
    assert [s["required"] for s in shown["statements"]] == [True, False, None, None, None, True, True]


def test_private_text_drops_only_the_word_government():
    private = [s["text"] for s in _shown("private")["statements"]]
    assert all("government" not in text for text in private)
    assert private == [text.replace("government ", "") for text in PUBLISHED_GOVERNMENT]


@pytest.mark.parametrize("ownership", [None, "", "GOVERNMENT", "public"])
def test_unrecorded_ownership_is_refused_not_guessed(ownership):
    with pytest.raises(ec.DeclarationRefused) as refused:
        _shown(ownership)
    assert refused.value.code == "facility_ownership_unset"


def test_the_digest_changes_with_any_name_or_wording():
    base = _shown()["sha256"]
    assert _shown("private")["sha256"] != base
    other = ec.declaration(ownership="government", health_worker="Nurse Shweta", beneficiary="Other")
    assert other["sha256"] != base


async def test_desk_gets_the_patient_and_staff_names_and_another_facility_gets_404(desk):  # noqa: F811
    shown = await desk["client"].get(
        "/abdm/abha/enrol/consent", params={"patient_id": str(desk["patient"].id)})
    assert shown.status_code == 200, shown.text
    texts = [s["text"] for s in shown.json()["declaration"]["statements"]]
    assert texts[5].startswith(f"I, {desk['staff'].full_name}, confirm")
    assert texts[6].startswith(f"I, {desk['patient'].full_name}, have been explained")
    elsewhere = await desk["client"].get(
        "/abdm/abha/enrol/consent", params={"patient_id": str(uuid.uuid4())})
    assert elsewhere.status_code == 404


async def test_unset_facility_ownership_blocks_the_consent_with_409(desk):  # noqa: F811
    desk["facility"].ownership = None
    await desk["db"].commit()
    shown = await desk["client"].get(
        "/abdm/abha/enrol/consent", params={"patient_id": str(desk["patient"].id)})
    assert shown.status_code == 409
    assert shown.json()["detail"]["code"] == "facility_ownership_unset"


async def _request(desk, consent):  # noqa: F811
    return await desk["client"].post("/abdm/abha/enrol/aadhaar/request-otp", json={
        "patient_id": str(desk["patient"].id), "aadhaar": AADHAAR, "consent": consent})


@pytest.mark.parametrize(
    ("ticks", "code"),
    [
        ({"aadhaar_sharing": False}, "enrolment_consent_refused"),
        ({"health_worker": False}, "enrolment_consent_refused"),
        ({"beneficiary": False}, "enrolment_consent_refused"),
        ({"other_document": True}, "enrolment_other_document_selected"),
    ],
)
async def test_required_ticks_are_checked_before_abdm_is_contacted(desk, ticks, code):  # noqa: F811
    response = await _request(desk, await consent_for(desk, **ticks))
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == code
    assert desk["gateway"].calls == []
    assert AADHAAR not in response.text


async def test_a_missing_statement_is_incomplete(desk):  # noqa: F811
    consent = await consent_for(desk)
    del consent["statements"]["anonymised_use"]
    response = await _request(desk, consent)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "enrolment_declaration_incomplete"
    assert desk["gateway"].calls == []


async def test_text_changed_after_display_is_not_recorded(desk):  # noqa: F811
    consent = await consent_for(desk)
    desk["patient"].full_name = "Renamed Patient"
    await desk["db"].commit()
    response = await _request(desk, consent)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "enrolment_declaration_changed"
    assert desk["gateway"].calls == []


async def test_optional_statements_may_be_declined_and_every_tick_is_audited(desk):  # noqa: F811
    desk["gateway"].responses = [{"txnId": "abdm-txn-1"}]
    consent = await consent_for(desk, link_records=False, anonymised_use=False)
    response = await _request(desk, consent)
    assert response.status_code == 200, response.text
    row = (await desk["db"].execute(
        select(AuditLog).where(AuditLog.resource_type == "abha_enrolment_consent"))).scalar_one()
    assert row.new_value["declaration_sha256"] == consent["declaration_sha256"]
    assert row.new_value["declaration_version"] == ec.DECLARATION_VERSION
    assert row.new_value["ownership"] == "government"
    assert row.new_value["statements"] == {
        "aadhaar_sharing": True, "other_document": False, "link_records": False,
        "share_for_care": True, "anonymised_use": False, "health_worker": True, "beneficiary": True,
    }
    assert AADHAAR not in str(row.new_value)


def test_hindi_is_the_same_seven_statements_with_the_same_rules():
    english, hindi = _shown(), ec.declaration(
        ownership="government", health_worker="Nurse Shweta", beneficiary="Aarav Sharma", language="hi")
    assert hindi["language"] == "hi" and hindi["notice"] and english["notice"] is None
    assert [(s["id"], s["ticked"], s["required"]) for s in hindi["statements"]] == [
        (s["id"], s["ticked"], s["required"]) for s in english["statements"]]
    texts = [s["text"] for s in hindi["statements"]]
    assert hindi["intro"].startswith("मैं एतद्द्वारा")
    assert "Nurse Shweta" in texts[5] and "Aarav Sharma" in texts[6]
    assert "सरकारी" in texts[2] and "सरकारी" in texts[4]
    assert hindi["sha256"] != english["sha256"], "the digest pins the language shown"


def test_hindi_for_a_private_facility_drops_only_the_word_government():
    government = [s["text"] for s in ec.declaration(
        ownership="government", health_worker="W", beneficiary="B", language="hi")["statements"]]
    private = [s["text"] for s in ec.declaration(
        ownership="private", health_worker="W", beneficiary="B", language="hi")["statements"]]
    assert all("सरकारी" not in text for text in private)
    assert private == [text.replace("सरकारी ", "") for text in government]


def test_a_language_without_a_translation_is_refused():
    with pytest.raises(ec.DeclarationRefused) as refused:
        ec.declaration(ownership="government", health_worker="W", beneficiary="B", language="ta")
    assert refused.value.code == "enrolment_consent_language_unavailable"


async def test_the_desk_can_show_and_record_the_hindi_consent(desk):  # noqa: F811
    shown = await desk["client"].get(
        "/abdm/abha/enrol/consent", params={"patient_id": str(desk["patient"].id), "language": "hi"})
    assert shown.status_code == 200, shown.text
    declaration = shown.json()["declaration"]
    assert declaration["language"] == "hi" and "HealthDoc" in declaration["notice"]
    desk["gateway"].responses = [{"txnId": "abdm-txn-1"}]
    statements = {row["id"]: row["ticked"] for row in declaration["statements"]}
    statements.update({"health_worker": True, "beneficiary": True})
    consent = {"granted": True, "code": "abha-enrollment", "version": "1.4", "language": "hi",
               "statements": statements, "declaration_sha256": declaration["sha256"]}
    response = await _request(desk, consent)
    assert response.status_code == 200, response.text
    row = (await desk["db"].execute(
        select(AuditLog).where(AuditLog.resource_type == "abha_enrolment_consent"))).scalar_one()
    assert row.new_value["language"] == "hi"
    assert row.new_value["declaration_sha256"] == declaration["sha256"]


async def test_english_ticks_against_the_hindi_text_are_not_recorded(desk):  # noqa: F811
    consent = await consent_for(desk)  # English digest
    consent["language"] = "hi"
    response = await _request(desk, consent)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "enrolment_declaration_changed"

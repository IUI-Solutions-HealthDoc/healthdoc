"""The HIU asks for and accepts all eight ABDM record types, not only ours.

M3 HIU_FLOW_102 lets a consent request carry "all or any of the 7 Health Info
types", and HIU_FLOW_111/112 fetch an Immunization record and a Health
Document record. HealthDoc builds five types as a HIP; another HIP's
immunization or scanned document must still be requestable and viewable.
"""

import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.integrations.abdm.hip import gateway as hip_gw
from app.integrations.abdm.hiu import gateway as hiu_gw
from app.integrations.abdm.hiu import records, service
from app.integrations.abdm.hiu.models import AbdmReceivedBundle
from tests.integrations.test_abdm_gateway_calls import REQUESTER, stub  # noqa: F401
from tests.integrations.test_abdm_hiu_key_lifecycle import ACTOR, FACILITY
from tests.integrations.test_abdm_received_records import (  # noqa: F401
    hiu_db,
    push,
    receive,
    received_case,
)

#: The M3 workbook's seven, and Invoice: NHA's own refusal lists all eight
#: ("Invalid HIType, it must be in ...,WellnessRecord,Invoice").
EIGHT = {
    "OPConsultation",
    "Prescription",
    "DiagnosticReport",
    "DischargeSummary",
    "ImmunizationRecord",
    "HealthDocumentRecord",
    "WellnessRecord",
    "Invoice",
}
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def test_the_hiu_vocabulary_is_the_eight_hi_types_and_wider_than_what_we_build():
    assert hiu_gw.REQUESTABLE_HI_TYPES == EIGHT
    assert hip_gw.HI_TYPES < hiu_gw.REQUESTABLE_HI_TYPES
    assert set(records.PROFILES.values()) == EIGHT


async def test_a_consent_request_may_name_all_eight_types(stub):  # noqa: F811
    now = datetime.now(UTC)
    await hiu_gw.request_consent(
        service_id="SBXID_TEST_HIU",
        abha_address="ram@sbx",
        hi_types=sorted(EIGHT),
        date_from=now - timedelta(days=30),
        date_to=now,
        expiry=now + timedelta(days=1),
        requester=REQUESTER,
    )
    assert set(stub.last["json"]["consent"]["hiTypes"]) == EIGHT


@pytest.mark.parametrize("unknown", ["NotARealType", "invoice"])
async def test_a_type_outside_the_eight_is_refused_before_the_wire(stub, unknown):  # noqa: F811
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="Unknown ABDM health-information type"):
        await hiu_gw.request_consent(
        service_id="SBXID_TEST_HIU",
            abha_address="ram@sbx",
            hi_types=["ImmunizationRecord", unknown],
            date_from=now - timedelta(days=30),
            date_to=now,
            expiry=now + timedelta(days=1),
            requester=REQUESTER,
        )
    assert stub.calls == []


async def test_service_type_check_refuses_only_outside_the_eight(hiu_db):  # noqa: F811
    with pytest.raises(service.HiuError) as refused:
        await service.create_consent_request(
            hiu_db, facility_id=FACILITY, patient_id=None, abha_address="ram@sbx",
            purpose_code="CAREMGT", hi_types=["NotARealType"],
            date_range_from=datetime.now(UTC) - timedelta(days=1),
            date_range_to=datetime.now(UTC),
            requested_expiry=datetime.now(UTC) + timedelta(days=1),
            created_by=ACTOR,
        )
    assert refused.value.code == "unsupported_hi_type"
    with pytest.raises(service.HiuError) as later:
        await service.create_consent_request(
            hiu_db, facility_id=FACILITY, patient_id=None, abha_address="ram@sbx",
            purpose_code="CAREMGT", hi_types=["ImmunizationRecord", "HealthDocumentRecord"],
            date_range_from=datetime.now(UTC) - timedelta(days=1),
            date_range_to=datetime.now(UTC),
            requested_expiry=datetime.now(UTC) + timedelta(days=1),
            created_by=ACTOR,
        )
    # Past the type check: it now stops on the missing patient instead.
    assert later.value.code != "unsupported_hi_type"


def _document(case, profile: str, clinical: dict) -> dict:
    bundle = {
        "resourceType": "Bundle",
        "type": "document",
        "entry": [
            {
                "fullUrl": "urn:uuid:composition",
                "resource": {
                    "resourceType": "Composition",
                    "status": "final",
                    "date": case.now.isoformat(),
                    "meta": {"profile": [records.PROFILE_ROOT + profile]},
                    "subject": {"reference": "urn:uuid:patient"},
                    "title": "Synthetic external record",
                    "section": [
                        {"entry": [{"reference": f"{clinical['resourceType']}/{clinical['id']}"}]}
                    ],
                },
            },
            case.bundle["entry"][1],
            {"resource": clinical},
        ],
    }
    return bundle


def _immunization(case) -> dict:
    return {
        "resourceType": "Immunization",
        "id": "i1",
        "status": "completed",
        "patient": {"reference": "Patient/p1"},
        "vaccineCode": {"text": "Synthetic vaccine"},
        "occurrenceDateTime": case.now.isoformat(),
    }


def _scanned_document() -> dict:
    return {
        "resourceType": "DocumentReference",
        "id": "d1",
        "status": "current",
        "subject": {"reference": "Patient/p1"},
        "content": [
            {
                "attachment": {
                    "contentType": "application/pdf",
                    "data": base64.b64encode(PDF).decode(),
                    "hash": base64.b64encode(
                        hashlib.sha1(PDF, usedforsecurity=False).digest()
                    ).decode(),
                    "title": "Synthetic scanned report",
                }
            }
        ],
    }


@pytest.mark.parametrize(
    ("hi_type", "profile", "clinical"),
    [
        ("ImmunizationRecord", "ImmunizationRecord", "immunization"),
        ("HealthDocumentRecord", "HealthDocumentRecord", "document"),
    ],
)
async def test_another_hips_immunization_and_scanned_document_are_viewable(
    received_case, hi_type, profile, clinical  # noqa: F811
):
    case = received_case
    case.artefact.hi_types = [hi_type]
    resource = _immunization(case) if clinical == "immunization" else _scanned_document()
    bundle = _document(case, profile, resource)
    await receive(case, push(case, bundle))
    receipt = (await case.db.execute(select(AbdmReceivedBundle))).scalar_one()
    assert receipt.status == "stored"
    assert (
        await records.read_record(case.db, receipt.id, facility_id=FACILITY, actor_id=ACTOR)
        == bundle
    )


async def test_an_immunization_for_another_patient_is_still_refused(received_case):  # noqa: F811
    case = received_case
    case.artefact.hi_types = ["ImmunizationRecord"]
    resource = _immunization(case)
    resource["patient"] = {"reference": "Patient/other"}
    with pytest.raises(HTTPException):
        await receive(case, push(case, _document(case, "ImmunizationRecord", resource)))
    receipts = (await case.db.execute(select(AbdmReceivedBundle))).scalars().all()
    assert all(row.content_encrypted is None for row in receipts)


async def test_an_unconsented_new_type_is_refused(received_case):  # noqa: F811
    case = received_case  # granted OPConsultation only
    with pytest.raises(HTTPException):
        await receive(case, push(case, _document(case, "ImmunizationRecord", _immunization(case))))

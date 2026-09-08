"""An authenticated cipher is not proof of consented clinical content."""

import copy
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.common.security import decrypt_pii
from app.integrations.abdm import external_router, job_runner, jobs
from app.integrations.abdm.contracts_v3 import HealthInformationPush
from app.integrations.abdm.hiu import records, service, worker
from app.integrations.abdm.hiu import router as hiu_router
from app.integrations.abdm.hiu.models import AbdmConsentRequest, AbdmReceivedBundle
from app.outbox.models import OutboxEvent
from tests.integrations.test_abdm_hiu_key_lifecycle import (
    ACTOR,
    FACILITY,
    _encrypt_plaintext_as_hip,
    _granted_artefact,
)
from tests.integrations.test_abdm_hiu_key_lifecycle import (
    hiu_db as hiu_fixture,
)

hiu_db = hiu_fixture


@pytest.fixture
async def received_case(hiu_db, monkeypatch):
    now = datetime.now(UTC)
    artefact = await _granted_artefact(hiu_db)
    artefact.date_range_from = now - timedelta(days=1)
    artefact.date_range_to = now + timedelta(minutes=1)
    artefact.expires_at = now + timedelta(days=1)
    row, wire = await service.begin_hi_request(
        hiu_db, facility_id=FACILITY, artefact=artefact, created_by=ACTOR, now=now
    )
    row.transaction_id = str(uuid.uuid4())
    bundle = {
        "resourceType": "Bundle",
        "type": "document",
        "entry": [
            {
                "fullUrl": "urn:uuid:composition",
                "resource": {
                    "resourceType": "Composition",
                    "status": "final",
                    "date": now.isoformat(),
                    "meta": {"profile": [records.PROFILE_ROOT + "OPConsultRecord"]},
                    "subject": {"reference": "urn:uuid:patient"},
                    "title": "Synthetic external consultation",
                },
            },
            {
                "fullUrl": "urn:uuid:patient",
                "resource": {
                    "resourceType": "Patient",
                    "id": "p1",
                    "identifier": [
                        {"system": "https://healthid.abdm.gov.in", "value": "12345678901234"}
                    ],
                },
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "c1",
                    "subject": {"reference": "Patient/p1"},
                }
            },
        ],
    }
    factory = async_sessionmaker(hiu_db.bind, expire_on_commit=False)
    monkeypatch.setattr(job_runner, "SessionLocal", factory)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker.gateway, "notify_hi_receipt", AsyncMock())
    await hiu_db.flush()
    return SimpleNamespace(
        db=hiu_db, artefact=artefact, request=row, wire=wire, bundle=bundle, now=now
    )


def push(case, bundle=None, *, reference="visit-1", pages=1):
    ciphertext, hip = _encrypt_plaintext_as_hip(json.dumps(bundle or case.bundle), case.wire)
    hip["dhPublicKey"]["expiry"] = (case.now + timedelta(hours=1)).isoformat()
    return HealthInformationPush.model_validate(
        {
            "transactionId": case.request.transaction_id,
            "pageNumber": 0,
            "pageCount": pages,
            "entries": [
                {
                    "content": ciphertext,
                    "media": "application/fhir+json",
                    "careContextReference": reference,
                }
            ],
            "keyMaterial": hip,
        }
    )


async def receive(case, payload=None):
    return await external_router.receive_health_information(payload or push(case), case.db)


async def test_received_content_is_encrypted_and_never_enters_general_outbox(received_case):
    case = received_case
    await receive(case)
    receipt = (await case.db.execute(select(AbdmReceivedBundle))).scalar_one()
    assert receipt.content_encrypted is not None
    assert b"Synthetic external" not in bytes(receipt.content_encrypted)
    assert (await case.db.execute(select(OutboxEvent))).scalars().all() == []
    assert "content_encrypted" in receipt.__audit_exclude_fields__
    assert case.request.private_key_encrypted is None
    assert case.request.status == "received"
    assert (
        await records.read_record(case.db, receipt.id, facility_id=FACILITY, actor_id=ACTOR)
        == case.bundle
    )
    with pytest.raises(InvalidTag):
        decrypt_pii(bytes(receipt.content_encrypted), associated_data=b"another-receipt")


@pytest.mark.parametrize(
    "defect",
    [
        "patient",
        "composition_subject",
        "clinical_subject",
        "second_patient",
        "context",
        "profile",
        "type",
        "date",
        "draft",
        "unbound",
        "raw_patient",
        "source_hip",
        "facility",
        "revoked",
        "expired",
        "missing_expiry",
        "contained",
        "malformed_subject",
        "huge_entry_set",
    ],
)
async def test_mismatched_content_or_authority_never_becomes_a_viewable_record(
    received_case, defect
):
    case = received_case
    bundle = copy.deepcopy(case.bundle)
    composition, patient, condition = (entry["resource"] for entry in bundle["entry"])
    reference = "visit-1"
    if defect == "patient":
        patient["identifier"][0]["value"] = "99999999999999"
    elif defect == "composition_subject":
        composition["subject"]["reference"] = "Patient/other"
    elif defect == "clinical_subject":
        condition["subject"]["reference"] = "Patient/other"
    elif defect == "second_patient":
        bundle["entry"].append({"resource": {"resourceType": "Patient", "id": "other"}})
    elif defect == "context":
        reference = "unconsented"
    elif defect == "profile":
        composition["meta"]["profile"] = [records.PROFILE_ROOT + "InventedRecord"]
    elif defect == "type":
        composition["meta"]["profile"] = [records.PROFILE_ROOT + "PrescriptionRecord"]
    elif defect == "date":
        composition["date"] = (case.now - timedelta(days=2)).isoformat()
    elif defect == "draft":
        composition["status"] = "preliminary"
    elif defect == "unbound":
        consent = await case.db.get(AbdmConsentRequest, case.artefact.consent_request_id)
        consent.patient_id = None
    elif defect in {"raw_patient", "source_hip"}:
        raw = copy.deepcopy(case.artefact.raw_artefact)
        raw["consentDetail"]["patient" if defect == "raw_patient" else "hip"] = {
            "id": "other@sbx" if defect == "raw_patient" else ""
        }
        case.artefact.raw_artefact = raw
    elif defect == "facility":
        case.artefact.facility_id = uuid.uuid4()
    elif defect == "revoked":
        case.artefact.status = "revoked"
    elif defect == "expired":
        case.artefact.expires_at = case.now - timedelta(seconds=1)
    elif defect == "missing_expiry":
        case.artefact.expires_at = None
    elif defect == "contained":
        condition["contained"] = [{"resourceType": "Patient", "id": "hidden"}]
    elif defect == "malformed_subject":
        composition["subject"]["reference"] = {"not": "a string"}
    elif defect == "huge_entry_set":
        bundle["entry"] *= 334
    with pytest.raises(HTTPException) as caught:
        await receive(case, push(case, bundle, reference=reference))
    assert caught.value.status_code in {403, 422}
    receipts = (await case.db.execute(select(AbdmReceivedBundle))).scalars().all()
    assert all(row.status != "stored" and row.content_encrypted is None for row in receipts)
    assert (await case.db.execute(select(OutboxEvent))).scalars().all() == []


@pytest.mark.parametrize(
    "defect", ["other_facility", "other_clinician", "revoked", "expired", "unlinked"]
)
async def test_view_rechecks_current_access(received_case, defect):
    case = received_case
    await receive(case)
    receipt = (await case.db.execute(select(AbdmReceivedBundle))).scalar_one()
    facility, actor = FACILITY, ACTOR
    if defect == "other_facility":
        facility = uuid.uuid4()
    elif defect == "other_clinician":
        actor = uuid.uuid4()
    elif defect == "revoked":
        case.artefact.status = "revoked"
    elif defect == "expired":
        case.artefact.expires_at = case.now - timedelta(seconds=1)
    else:
        grant = await records.grant_for(case.db, case.request, now=case.now)
        grant.patient.abha_linked_at = None
    with pytest.raises(records.RecordRefused):
        await records.read_record(case.db, receipt.id, facility_id=facility, actor_id=actor)


async def test_cleanup_erases_bytes_without_traffic_and_keeps_receipt(received_case):
    case = received_case
    await receive(case)
    receipt = (await case.db.execute(select(AbdmReceivedBundle))).scalar_one()
    ident, digest = receipt.id, receipt.content_sha256
    case.artefact.expires_at = case.now - timedelta(seconds=1)
    await case.db.commit()
    assert await job_runner.cleanup_expired_keys() == 1
    await case.db.refresh(receipt)
    assert receipt.id == ident and receipt.content_sha256 == digest
    assert receipt.content_encrypted is None and receipt.content_key_version is None
    assert receipt.erased_at is not None
    assert await job_runner.cleanup_expired_keys() == 0


async def test_exact_replay_is_idempotent_but_changed_page_is_not(received_case):
    case = received_case
    payload = push(case)
    await receive(case, payload)
    assert (await receive(case, payload)).status_code == 202
    changed = payload.model_copy(deep=True)
    changed.entries[0].content += "tampered"
    with pytest.raises(HTTPException) as caught:
        await receive(case, changed)
    assert caught.value.status_code == 409
    assert len((await case.db.execute(select(AbdmReceivedBundle))).scalars().all()) == 1


async def test_rejected_entry_does_not_become_success_on_retry(received_case):
    case = received_case
    payload = push(case, reference="not-authorized")
    with pytest.raises(HTTPException) as first:
        await receive(case, payload)
    assert first.value.status_code == 422
    with pytest.raises(HTTPException) as second:
        await receive(case, payload)
    assert second.value.status_code == 409
    assert case.request.status == "partial"


async def test_receipt_notification_is_restart_safe_and_does_not_need_retained_private_key(
    received_case,
):
    case = received_case
    await receive(case)
    await case.db.commit()
    ident = jobs.job_id("hiu_notify", case.request.id)
    worker.gateway.notify_hi_receipt.side_effect = RuntimeError("synthetic unavailable")
    assert await job_runner.run_once(ident)
    job = await case.db.get(jobs.AbdmJob, ident)
    assert job.status == "pending"
    assert case.request.status == "received" and case.request.private_key_encrypted is None
    job.available_at = case.now - timedelta(seconds=1)
    await case.db.commit()
    worker.gateway.notify_hi_receipt.side_effect = None
    assert await job_runner.run_once(ident)
    await case.db.refresh(job)
    assert job.status == "done"
    calls = worker.gateway.notify_hi_receipt.call_args_list
    assert calls[0].kwargs == calls[1].kwargs
    assert calls[1].kwargs["hip_id"] == "TEST-EXTERNAL-HIP"


async def test_workspace_is_requester_scoped_and_hides_revoked_content(received_case):
    case = received_case
    await receive(case)
    consent = await case.db.get(AbdmConsentRequest, case.artefact.consent_request_id)
    actor = SimpleNamespace(id=ACTOR, facility_id=FACILITY)
    page = await hiu_router.patient_workspace(
        consent.patient_id, actor, case.db, limit=20, offset=0
    )
    assert len(page.requests) == 1 and page.requests[0].transfers[0].records[0].available
    stranger = await hiu_router.patient_workspace(
        consent.patient_id,
        SimpleNamespace(id=uuid.uuid4(), facility_id=FACILITY),
        case.db,
        limit=20,
        offset=0,
    )
    assert stranger.requests == []
    case.artefact.status = "revoked"
    page = await hiu_router.patient_workspace(
        consent.patient_id, actor, case.db, limit=20, offset=0
    )
    assert not page.requests[0].transfers[0].records[0].available
    with pytest.raises(HTTPException) as denied:
        await hiu_router.patient_workspace(
            consent.patient_id,
            SimpleNamespace(id=ACTOR, facility_id=uuid.uuid4()),
            case.db,
            limit=20,
            offset=0,
        )
    assert denied.value.status_code == 404


async def test_request_mutations_persist_correlation_before_network_and_deduplicate(
    received_case, monkeypatch
):
    case = received_case
    monkeypatch.setattr(
        worker.gateway,
        "request_consent",
        AsyncMock(
            return_value=("unused", SimpleNamespace(body={"consentRequestId": "REMOTE-TEST"}))
        ),
    )
    monkeypatch.setattr(worker.gateway, "request_health_information", AsyncMock())
    consent = await case.db.get(AbdmConsentRequest, case.artefact.consent_request_id)
    actor = SimpleNamespace(id=ACTOR, facility_id=FACILITY)
    payload = hiu_router.ConsentRequestIn(
        patient_id=consent.patient_id,
        abha_address=consent.abha_address,
        purpose_code="CAREMGT",
        hi_types=["OPConsultation"],
        date_range_from=case.now - timedelta(days=1),
        date_range_to=case.now,
        requested_expiry=case.now + timedelta(days=1),
    )
    first = await hiu_router.create_consent_request(payload, actor, "consent-retry", case.db)
    second = await hiu_router.create_consent_request(payload, actor, "consent-retry", case.db)
    assert first.id == second.id
    row = await case.db.get(AbdmConsentRequest, first.id)
    assert row.gateway_request_id == str(jobs.job_id("hiu_consent", first.id))
    worker.gateway.request_consent.assert_not_awaited()
    await case.db.commit()
    assert await job_runner.run_once(jobs.job_id("hiu_consent", first.id))
    worker.gateway.request_consent.assert_awaited_once()
    assert worker.gateway.request_consent.call_args.kwargs["request_id"] == row.gateway_request_id
    altered = payload.model_copy(update={"hi_types": ["Prescription"]})
    with pytest.raises(HTTPException) as conflict:
        await hiu_router.create_consent_request(altered, actor, "consent-retry", case.db)
    assert conflict.value.status_code == 409
    first_data = await hiu_router.request_health_information(
        case.artefact.id, actor, "data-retry", case.db
    )
    second_data = await hiu_router.request_health_information(
        case.artefact.id, actor, "data-retry", case.db
    )
    assert first_data.id == second_data.id
    worker.gateway.request_health_information.assert_not_awaited()
    await case.db.commit()
    await job_runner.run_once(jobs.job_id("hiu_request", first_data.id))
    assert worker.gateway.request_health_information.call_args.kwargs[
        "date_from"
    ] == case.artefact.date_range_from.replace(tzinfo=None)

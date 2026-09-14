"""Synthetic M2 callbacks must not change patient/document scope on replay."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.integrations.abdm import callback_replies, external_router, job_runner, jobs
from app.integrations.abdm.callback_auth import GatewayCallback
from app.integrations.abdm.contracts_v3 import LinkConfirmCallback, LinkInitCallback
from app.integrations.abdm.hip import gateway, link_otp
from app.integrations.abdm.hip.models import AbdmCareContextLink
from app.integrations.abdm.hiu import worker as hiu_worker
from tests.integrations.test_abdm_document_exports import documents as documents_fixture
from tests.integrations.test_abdm_hip_link_operations import link_case as link_case_fixture

documents = documents_fixture
link_case = link_case_fixture


@pytest.fixture
async def mediated_case(db, link_case, monkeypatch):
    patient, contexts = link_case
    patient.mobile = "+919876543210"
    link = AbdmCareContextLink(
        id=uuid.uuid4(),
        facility_id=patient.facility_id,
        patient_id=patient.id,
        abha_address=patient.abha_address,
        link_ref_number=str(uuid.uuid4()),
        transaction_id=str(uuid.uuid4()),
        gateway_request_id=str(uuid.uuid4()),
        care_context_references=[contexts[0].reference],
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db.add(link)
    await db.commit()
    monkeypatch.setattr(link_otp, "issue", AsyncMock(return_value="******3210"))
    monkeypatch.setattr(link_otp, "verify", AsyncMock())
    monkeypatch.setattr(link_otp, "_get_hmac_key", lambda: b"synthetic-proof-key" * 2)
    monkeypatch.setattr(gateway, "respond_to_link_init", AsyncMock())
    monkeypatch.setattr(gateway, "respond_to_link_confirm_groups", AsyncMock())
    monkeypatch.setattr(
        callback_replies, "SessionLocal", async_sessionmaker(db.bind, expire_on_commit=False)
    )
    monkeypatch.setattr(
        hiu_worker, "get_settings", lambda: SimpleNamespace(abdm_hfr_facility_id="TEST-HFR")
    )
    return patient, contexts, link


def callback():
    return GatewayCallback(str(uuid.uuid4()), datetime.now(UTC), "HIP-TEST")


def confirmation(link):
    return LinkConfirmCallback.model_validate(
        {"confirmation": {"linkRefNumber": link.link_ref_number, "token": "123456"}}
    )


def initiation(patient, context, link):
    return LinkInitCallback.model_validate(
        {
            "transactionId": link.transaction_id,
            "abhaAddress": patient.abha_address,
            "patient": [
                {
                    "referenceNumber": patient.uhid,
                    "display": patient.full_name,
                    "careContexts": [
                        {"referenceNumber": context.reference, "display": context.display}
                    ],
                    "hiType": context.hi_type,
                    "count": 1,
                }
            ],
        }
    )


async def test_confirm_cannot_access_another_configured_facility(db, mediated_case, monkeypatch):
    _, _, link = mediated_case
    monkeypatch.setattr(external_router, "_facility_id", AsyncMock(return_value=uuid.uuid4()))
    with pytest.raises(HTTPException) as caught:
        await external_router.link_confirm(confirmation(link), callback(), db)
    assert caught.value.status_code == 404
    link_otp.verify.assert_not_awaited()
    gateway.respond_to_link_confirm_groups.assert_not_awaited()
    assert link.status == "pending"


@pytest.mark.parametrize("change", ["deleted", "merged", "address", "facility"])
async def test_confirm_rechecks_patient_binding_before_spending_otp(db, mediated_case, change):
    patient, _, link = mediated_case
    if change == "deleted":
        patient.deleted_at = datetime.now(UTC)
    elif change == "merged":
        patient.merged_into_patient_id = uuid.uuid4()
    elif change == "address":
        patient.abha_address = "changed-synthetic@sbx"
    else:
        patient.facility_id = uuid.uuid4()
    await db.flush()
    with pytest.raises(HTTPException) as caught:
        await external_router.link_confirm(confirmation(link), callback(), db)
    assert caught.value.status_code == 404
    link_otp.verify.assert_not_awaited()
    gateway.respond_to_link_confirm_groups.assert_not_awaited()
    assert link.status == "pending"


async def test_confirm_refuses_partial_document_selection_before_spending_otp(db, mediated_case):
    _, _, link = mediated_case
    link.care_context_references = [*link.care_context_references, "encounter/missing"]
    await db.flush()
    with pytest.raises(HTTPException) as caught:
        await external_router.link_confirm(confirmation(link), callback(), db)
    assert caught.value.status_code == 409
    link_otp.verify.assert_not_awaited()
    gateway.respond_to_link_confirm_groups.assert_not_awaited()
    assert link.status == "pending"


async def test_init_replay_cannot_change_the_document_selection(db, mediated_case):
    patient, contexts, link = mediated_case
    original = list(link.care_context_references)
    with pytest.raises(HTTPException) as caught:
        await external_router.link_init(initiation(patient, contexts[1], link), callback(), db)
    assert caught.value.status_code == 409
    assert link.care_context_references == original
    link_otp.issue.assert_not_awaited()


@pytest.mark.parametrize("state", ["expired", "failed", "confirmed", "past_expiry"])
async def test_init_replay_cannot_restart_a_closed_or_expired_operation(db, mediated_case, state):
    patient, contexts, link = mediated_case
    if state == "past_expiry":
        link.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        link.status = state
    await db.flush()
    previous_expiry = link.expires_at
    with pytest.raises(HTTPException) as caught:
        await external_router.link_init(initiation(patient, contexts[0], link), callback(), db)
    assert caught.value.status_code in {409, 410}
    assert link.expires_at == previous_expiry
    link_otp.issue.assert_not_awaited()


async def test_confirmation_acknowledges_exact_selected_documents(db, mediated_case):
    patient, contexts, link = mediated_case
    response = await external_router.link_confirm(confirmation(link), callback(), db)
    assert response.status_code == 202
    assert link.status == "confirmed" and link.confirmed_at is not None
    gateway.respond_to_link_confirm_groups.assert_not_awaited()
    await db.commit()
    ack = (await db.execute(select(jobs.AbdmJob))).scalar_one()
    assert ack.kind == "callback_ack"
    await job_runner.run_once(ack.id)
    groups = gateway.respond_to_link_confirm_groups.call_args.kwargs[
        "patient_groups"
    ]
    assert [group["referenceNumber"] for group in groups] == [patient.uhid]
    assert [row["referenceNumber"] for group in groups for row in group["careContexts"]] == [
        contexts[0].reference
    ]


async def test_ack_outage_retries_committed_proof_without_reconsuming_otp(db, mediated_case):
    _, _, link = mediated_case
    payload, event = confirmation(link), callback()
    ack = gateway.respond_to_link_confirm_groups
    ack.side_effect = RuntimeError("Synthetic gateway outage")
    await external_router.link_confirm(payload, event, db)
    await db.commit()
    reply = (await db.execute(select(jobs.AbdmCallbackReply))).scalar_one()
    assert reply.kind == "hip_link_confirm"
    assert len(reply.payload_sha256) == 64
    assert reply.subject_ids == link.care_context_references
    ack_job = (await db.execute(select(jobs.AbdmJob))).scalar_one()
    await job_runner.run_once(ack_job.id)
    await db.refresh(ack_job)
    await db.refresh(link)
    assert ack_job.status == "pending"
    assert link.status == "confirmed"
    first_wire = dict(ack.call_args.kwargs)
    # Committed exact confirmation replay remains valid after OTP expiry.
    link.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()
    await external_router.link_confirm(payload, event, db)
    link_otp.verify.assert_awaited_once()
    ack_job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    ack.side_effect = None
    await job_runner.run_once(ack_job.id)
    await db.refresh(ack_job)
    assert ack_job.status == "done"
    assert ack.call_args.kwargs == first_wire
    assert (await db.execute(select(jobs.AbdmJob.kind))).scalars().all() == ["callback_ack"]


@pytest.mark.parametrize("change", ["otp", "callback_id", "documents"])
async def test_committed_confirmation_cannot_accept_changed_proof(db, mediated_case, change):
    _, contexts, link = mediated_case
    payload, event = confirmation(link), callback()
    await external_router.link_confirm(payload, event, db)
    await db.commit()
    if change == "otp":
        payload.confirmation.token = "000000"
    elif change == "callback_id":
        event = callback()
    else:
        link.care_context_references = [contexts[1].reference]
        await db.flush()
    with pytest.raises(HTTPException) as caught:
        await external_router.link_confirm(payload, event, db)
    assert caught.value.status_code == 409
    link_otp.verify.assert_awaited_once()
    gateway.respond_to_link_confirm_groups.assert_not_awaited()


async def test_proof_and_ack_intent_rollback_together(db, mediated_case, monkeypatch):
    _, _, link = mediated_case
    link_id = link.id
    payload, event = confirmation(link), callback()
    schedule = callback_replies.schedule
    monkeypatch.setattr(callback_replies, "schedule", AsyncMock(side_effect=RuntimeError("DB fault")))
    with pytest.raises(RuntimeError, match="DB fault"):
        await external_router.link_confirm(payload, event, db)
    await db.rollback()
    persisted = await db.get(AbdmCareContextLink, link_id)
    assert persisted.status == "pending" and persisted.confirmed_at is None
    assert (await db.execute(select(jobs.AbdmJob))).scalars().all() == []
    monkeypatch.setattr(callback_replies, "schedule", schedule)
    await external_router.link_confirm(payload, event, db)
    await db.commit()
    first, retry = link_otp.verify.call_args_list
    assert first.kwargs == retry.kwargs
    assert first.kwargs["confirmation_id"] == event.request_id


async def test_ack_dispatch_rechecks_binding_before_network(db, mediated_case):
    patient, _, link = mediated_case
    await external_router.link_confirm(confirmation(link), callback(), db)
    await db.commit()
    ack_job = (await db.execute(select(jobs.AbdmJob))).scalar_one()
    patient.abha_address = "changed-before-dispatch@sbx"
    await db.commit()
    await job_runner.run_once(ack_job.id)
    gateway.respond_to_link_confirm_groups.assert_not_awaited()
    await db.refresh(ack_job)
    assert ack_job.status != "done"

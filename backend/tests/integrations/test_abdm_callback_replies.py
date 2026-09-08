"""Network/commit crash boundaries with real persisted acknowledgement intent."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.integrations.abdm import callback_replies, external_router, job_runner, jobs
from app.integrations.abdm.callback_auth import GatewayCallback
from app.integrations.abdm.contracts_v3 import HiuConsentNotifyCallback
from app.integrations.abdm.hip.models import AbdmHipHealthInformationRequest
from app.integrations.abdm.hiu import worker as hiu_worker
from app.integrations.abdm.hiu.models import AbdmConsentRequest
from tests.integrations.test_abdm_hiu_key_lifecycle import FACILITY, _granted_artefact
from tests.integrations.test_abdm_hiu_key_lifecycle import hiu_db as hiu_fixture
from tests.integrations.test_abdm_transfer_scope import transfer_case as transfer_fixture

hiu_db = hiu_fixture
transfer_case = transfer_fixture


async def test_hip_ack_failure_cannot_lose_the_request_or_start_transfer(db, transfer_case):
    payload, callback, _, pushes = transfer_case
    ack = external_router.hip_gateway.acknowledge_hi_request
    ack.side_effect = RuntimeError("Synthetic acknowledgement outage")
    await external_router.hip_health_information_request(payload, BackgroundTasks(), callback, db)
    ack.assert_not_awaited()
    request = (await db.execute(select(AbdmHipHealthInformationRequest))).scalar_one()
    ack_job = (await db.execute(select(jobs.AbdmJob))).scalar_one()
    assert ack_job.kind == "callback_ack"
    assert await db.get(jobs.AbdmJob, jobs.job_id("hip_transfer", request.id)) is None
    await job_runner.run_once(ack_job.id)
    pushes.assert_not_awaited()
    await db.refresh(ack_job)
    assert ack_job.status == "pending"
    first_wire = dict(ack.call_args.kwargs)
    ack_job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    ack.side_effect = None
    await job_runner.run_once(ack_job.id)
    assert ack.call_args.kwargs == first_wire
    await job_runner.run_once(jobs.job_id("hip_transfer", request.id))
    assert pushes.await_count == 1


async def test_changed_transaction_replay_is_refused_without_another_job(db, transfer_case):
    payload, callback, _, _ = transfer_case
    await external_router.hip_health_information_request(payload, BackgroundTasks(), callback, db)
    await external_router.hip_health_information_request(payload, BackgroundTasks(), callback, db)
    assert len((await db.execute(select(jobs.AbdmCallbackReply))).scalars().all()) == 1
    payload.hi_request.key_material.nonce = "changed-nonce"
    with pytest.raises(HTTPException) as caught:
        await external_router.hip_health_information_request(
            payload, BackgroundTasks(), callback, db
        )
    assert caught.value.status_code == 409
    assert len((await db.execute(select(jobs.AbdmJob))).scalars().all()) == 1


async def test_reply_intent_rolls_back_with_business_transaction(db, seed):
    dept, _, _ = seed
    await db.commit()
    payload = HiuConsentNotifyCallback.model_validate(
        {
            "notification": {"consentRequestId": "TEST-CONSENT", "status": "GRANTED"},
        }
    )
    await callback_replies.schedule(
        db,
        facility_id=dept.facility_id,
        kind="hiu_consent",
        gateway_request_id=str(uuid.uuid4()),
        payload=payload,
        subject_ids=["TEST-ARTEFACT"],
    )
    assert len((await db.execute(select(jobs.AbdmCallbackReply))).scalars().all()) == 1
    await db.rollback()
    assert (await db.execute(select(jobs.AbdmCallbackReply))).scalars().all() == []
    assert (await db.execute(select(jobs.AbdmJob))).scalars().all() == []


async def test_same_callback_id_cannot_change_content(db, seed):
    dept, _, _ = seed
    payload = HiuConsentNotifyCallback.model_validate(
        {
            "notification": {"consentRequestId": "TEST-CONSENT", "status": "GRANTED"},
        }
    )
    kwargs = dict(
        facility_id=dept.facility_id,
        kind="hiu_consent",
        gateway_request_id=str(uuid.uuid4()),
        payload=payload,
        subject_ids=["TEST-ARTEFACT"],
    )
    first = await callback_replies.schedule(db, **kwargs)
    assert await callback_replies.schedule(db, **kwargs) == first
    payload.notification.status = "REVOKED"
    with pytest.raises(HTTPException) as caught:
        await callback_replies.schedule(db, **kwargs)
    assert caught.value.status_code == 409


async def test_hiu_notification_survives_ack_and_fetch_outages_without_patient_content(
    hiu_db, monkeypatch
):
    db = hiu_db
    artefact = await _granted_artefact(db)
    artefact.expires_at = artefact.date_range_from = artefact.date_range_to = None
    artefact.hi_types = []
    consent = await db.get(AbdmConsentRequest, artefact.consent_request_id)
    consent.consent_request_id = str(uuid.uuid4())
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    for module in (job_runner, callback_replies, hiu_worker):
        monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(external_router, "_facility_id", AsyncMock(return_value=FACILITY))
    ack, fetch = AsyncMock(side_effect=RuntimeError("synthetic outage")), AsyncMock()
    monkeypatch.setattr(callback_replies.hiu_gateway, "acknowledge_consent_notification", ack)
    monkeypatch.setattr(hiu_worker.gateway, "fetch_consent_artefact", fetch)
    callback = GatewayCallback(str(uuid.uuid4()), datetime.now(UTC), "TEST-HIU")
    payload = HiuConsentNotifyCallback.model_validate(
        {
            "notification": {
                "consentRequestId": consent.consent_request_id,
                "status": "GRANTED",
                "consentArtefacts": [{"id": artefact.consent_artefact_id}],
            },
        }
    )
    await external_router.hiu_consent_notify(payload, callback, db)
    await db.commit()
    ack.assert_not_awaited()
    reply = (await db.execute(select(jobs.AbdmCallbackReply))).scalar_one()
    assert set(reply.__table__.columns.keys()) == {
        "id",
        "facility_id",
        "kind",
        "gateway_request_id",
        "payload_sha256",
        "subject_ids",
        "target_id",
        "created_at",
        "updated_at",
    }
    assert reply.subject_ids == [artefact.consent_artefact_id]
    ack_ident = jobs.job_id("callback_ack", reply.id)
    await job_runner.run_once(ack_ident)
    fetch.assert_not_awaited()
    ack_job = await db.get(jobs.AbdmJob, ack_ident)
    ack_job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    ack.side_effect = None
    await job_runner.run_once(ack_ident)
    assert ack.call_args_list[0].kwargs == ack.call_args_list[1].kwargs
    fetch_ident = jobs.job_id("hiu_fetch", artefact.id)
    fetch.side_effect = RuntimeError("Synthetic fetch outage")
    await job_runner.run_once(fetch_ident)
    fetch_job = await db.get(jobs.AbdmJob, fetch_ident)
    assert fetch_job.status == "pending"
    fetch_job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    fetch.side_effect = None
    await job_runner.run_once(fetch_ident)
    assert (
        fetch.call_args_list[0].kwargs
        == fetch.call_args_list[1].kwargs
        == {
            "consent_id": artefact.consent_artefact_id,
            "request_id": str(fetch_ident),
        }
    )

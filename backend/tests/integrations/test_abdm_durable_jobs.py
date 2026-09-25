import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select

from app.integrations.abdm import external_router, job_runner, jobs, operations
from app.integrations.abdm.hip import worker
from app.integrations.abdm.hip.models import AbdmHipHealthInformationRequest, AbdmHipTransferPage
from tests.integrations.test_abdm_transfer_scope import transfer_case as transfer_fixture

transfer_case = transfer_fixture


async def test_old_jobs_freeze_without_touching_new_work(db, seed):
    from types import SimpleNamespace

    dept, _, doctor = seed
    actor = SimpleNamespace(id=doctor.id, facility_id=dept.facility_id)
    old_id = await jobs.enqueue(
        db, kind="context_notify", target_id=uuid.uuid4(), facility_id=dept.facility_id
    )
    await db.commit()
    cutoff = datetime.now(UTC)
    new_id = await jobs.enqueue(
        db, kind="context_notify", target_id=uuid.uuid4(), facility_id=dept.facility_id
    )
    await db.commit()
    # SQLite's CURRENT_TIMESTAMP has only second precision. Set explicit
    # sides of the cutoff so this test proves the filter, not clock rounding.
    (await db.get(jobs.AbdmJob, old_id)).created_at = cutoff - timedelta(days=1)
    (await db.get(jobs.AbdmJob, new_id)).created_at = cutoff + timedelta(days=1)
    await db.commit()

    with pytest.raises(ValueError, match="no jobs frozen"):
        await jobs.freeze_pending_before(
            db, facility_id=dept.facility_id, before=cutoff, expected_count=2
        )
    assert (await db.get(jobs.AbdmJob, old_id)).status == "pending"
    assert (await db.get(jobs.AbdmJob, new_id)).status == "pending"

    assert await jobs.freeze_pending_before(
        db, facility_id=dept.facility_id, before=cutoff, expected_count=1
    ) == 1
    await db.commit()
    assert (await db.get(jobs.AbdmJob, old_id)).status == "frozen"
    assert await jobs.claim(db, ident=old_id) is None
    frozen = await operations.list_jobs(actor, db, status="frozen", offset=0, limit=50)
    assert [row.id for row in frozen] == [old_id]
    with pytest.raises(HTTPException) as caught:
        await operations.retry_job(old_id, actor, db, "frozen-retry")
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "job_frozen"
    assert (await jobs.claim(db, ident=new_id)).id == new_id


async def test_freeze_requires_aware_cutoff_and_positive_exact_count(db, seed):
    dept, _, _ = seed
    with pytest.raises(ValueError, match="UTC offset"):
        await jobs.freeze_pending_before(
            db, facility_id=dept.facility_id, before=datetime.now(), expected_count=1
        )
    with pytest.raises(ValueError, match="positive"):
        await jobs.freeze_pending_before(
            db, facility_id=dept.facility_id, before=datetime.now(UTC), expected_count=0
        )


async def test_operator_retry_is_facility_scoped_and_does_not_reset_active_jobs(db, seed):
    from types import SimpleNamespace

    dept, _, doctor = seed
    actor = SimpleNamespace(id=doctor.id, facility_id=dept.facility_id)
    ident = await jobs.enqueue(
        db, kind="hip_transfer", target_id=uuid.uuid4(), facility_id=dept.facility_id
    )
    job = await db.get(jobs.AbdmJob, ident)
    job.status, job.attempts, job.last_error = "dead", 5, "SyntheticFailure"
    await db.flush()
    assert len(await operations.list_jobs(actor, db, status="dead", offset=0, limit=50)) == 1
    stranger = SimpleNamespace(id=doctor.id, facility_id=uuid.uuid4())
    assert await operations.list_jobs(stranger, db, status="dead", offset=0, limit=50) == []
    with pytest.raises(HTTPException) as caught:
        await operations.retry_job(ident, stranger, db, "retry-one")
    assert caught.value.status_code == 404
    assert (await operations.retry_job(ident, actor, db, "retry-one")).status == "pending"
    assert job.attempts == 0
    job.attempts = 1
    assert (await operations.retry_job(ident, actor, db, "retry-two")).attempts == 1
    job.status, job.attempts = "dead", 5
    # A delayed HTTP replay must not reset a second exhausted delivery cycle.
    assert (await operations.retry_job(ident, actor, db, "retry-one")).status == "pending"
    assert job.status == "dead" and job.attempts == 5
    job.status = "leased"
    with pytest.raises(HTTPException) as caught:
        await operations.retry_job(ident, actor, db, "retry-three")
    assert caught.value.status_code == 409


async def test_expired_lease_is_reclaimed_and_stale_worker_cannot_finish(db, seed):
    dept, _, _ = seed
    ident = await jobs.enqueue(
        db, kind="hip_transfer", target_id=uuid.uuid4(), facility_id=dept.facility_id
    )
    await db.commit()
    first = await jobs.claim(db)
    old_token = first.lease_token
    old_attempts = first.attempts
    assert await jobs.claim(db) is None
    second = await jobs.claim(db, now=datetime.now(UTC) + timedelta(minutes=3))
    assert second.id == ident and second.lease_token != old_token and second.attempts == 2
    stale = jobs.AbdmJob(id=ident, lease_token=old_token, attempts=old_attempts)
    assert not await jobs.finish(db, stale)
    assert await jobs.finish(db, second)
    await jobs.enqueue(
        db, kind="hip_transfer", target_id=second.target_id, facility_id=dept.facility_id
    )
    assert await jobs.claim(db) is None


async def test_callback_work_survives_without_running_background_task(db, transfer_case):
    payload, callback, _, pushes = transfer_case
    await external_router.hip_health_information_request(payload, BackgroundTasks(), callback, db)
    pushes.assert_not_awaited()
    # No HTTP background task was executed; a separate polling session finds it.
    assert await job_runner.run_once()
    pushes.assert_not_awaited()  # First acknowledge the durable callback.
    assert await job_runner.run_once()
    assert pushes.await_count == 1


async def test_retry_reuses_frozen_ciphertext_and_does_not_rebuild(db, transfer_case, monkeypatch):
    payload, callback, _, pushes = transfer_case
    await external_router.hip_health_information_request(payload, BackgroundTasks(), callback, db)
    await job_runner.run_once()  # Acknowledge, then schedule transfer.
    row = (await db.execute(select(AbdmHipHealthInformationRequest))).scalar_one()
    request_id = row.id
    pushes.side_effect = worker.TransientTransferError("Synthetic transport outage")
    assert await job_runner.run_once()
    first_payload = pushes.call_args.args[1]
    assert len((await db.execute(select(AbdmHipTransferPage))).scalars().all()) == 1
    job = (
        await db.execute(select(jobs.AbdmJob).where(jobs.AbdmJob.kind == "hip_transfer"))
    ).scalar_one()
    job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    monkeypatch.setattr(
        worker, "_clinical_facts", AsyncMock(side_effect=AssertionError("Must not rebuild"))
    )
    pushes.side_effect = None
    assert await job_runner.run_once(job.id)
    assert pushes.call_args.args[1] == first_payload
    db.expire_all()
    assert (await db.get(AbdmHipHealthInformationRequest, request_id)).status == "delivered"


async def test_notification_retry_does_not_repeat_clinical_transfer(db, transfer_case, monkeypatch):
    payload, callback, _, pushes = transfer_case
    await external_router.hip_health_information_request(payload, BackgroundTasks(), callback, db)
    await job_runner.run_once()  # Acknowledge before transfer.
    await job_runner.run_once()
    notify = AsyncMock(side_effect=worker.TransferError("Synthetic gateway outage"))
    monkeypatch.setattr(worker, "_notify_gateway", notify)
    assert await job_runner.run_once()
    assert pushes.await_count == 1
    job = (
        await db.execute(select(jobs.AbdmJob).where(jobs.AbdmJob.kind == "hip_notify"))
    ).scalar_one()
    assert job.status == "pending"
    job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    notify.side_effect = None
    await job_runner.run_once(job.id)
    assert notify.await_count == 2 and pushes.await_count == 1


async def test_restart_after_first_page_skips_delivered_page_and_preserves_snapshot(
    db, transfer_case, monkeypatch
):
    from app.integrations.abdm.hip.models import AbdmHipConsentArtefact

    payload, callback, _, pushes = transfer_case
    artefact = (await db.execute(select(AbdmHipConsentArtefact))).scalar_one()
    payload.hi_request.date_range.from_ = worker._aware(artefact.date_range_from)
    payload.hi_request.date_range.to = worker._aware(artefact.date_range_to)
    await external_router.hip_health_information_request(payload, BackgroundTasks(), callback, db)
    await job_runner.run_once()  # Acknowledge before transfer.
    request = (await db.execute(select(AbdmHipHealthInformationRequest))).scalar_one()
    request_id = request.id
    ident = jobs.job_id("hip_transfer", request_id)
    pushes.side_effect = [None, worker.TransientTransferError("Synthetic interruption")]
    await job_runner.run_once(ident)
    initial_payloads = [call.args[1] for call in pushes.call_args_list]
    pages = (
        (await db.execute(select(AbdmHipTransferPage).order_by(AbdmHipTransferPage.page_number)))
        .scalars()
        .all()
    )
    assert len(pages) == 3
    assert [p.delivered_at is not None for p in pages] == [True, False, False]
    job = await db.get(jobs.AbdmJob, ident)
    job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()

    monkeypatch.setattr(
        worker,
        "_clinical_facts",
        AsyncMock(side_effect=AssertionError("Retry must use the persisted encrypted snapshot")),
    )
    pushes.reset_mock(side_effect=True)
    await job_runner.run_once(ident)
    retried_payloads = [call.args[1] for call in pushes.call_args_list]
    assert [p["pageNumber"] for p in retried_payloads] == [1, 2]
    assert retried_payloads[0] == initial_payloads[1]
    db.expire_all()
    request = await db.get(AbdmHipHealthInformationRequest, request_id)
    assert request.status == "delivered" and request.bundles_sent == "3"

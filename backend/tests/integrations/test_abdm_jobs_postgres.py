"""Actual row-lock contention; SQLite cannot prove worker exclusivity.

Only TEST_DATABASE_URL is allowed. A configured but unavailable/mismigrated
test database fails the test, instead of silently claiming a passing gate.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.audit.models import AuditLog
from app.integrations.abdm import callback_replies, jobs
from app.integrations.abdm.contracts_v3 import HiuConsentNotifyCallback
from app.users.models import Facility


@pytest_asyncio.fixture
async def pg_jobs():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL row-lock tests")
    assert make_url(url).get_backend_name() == "postgresql"
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    facility_id = uuid.uuid4()
    try:
        async with sessions() as db:
            db.add(
                Facility(
                    id=facility_id,
                    code=f"AJ{uuid.uuid4().hex[:8]}",
                    name="ABDM worker lock test",
                    state_code="TS",
                )
            )
            await db.commit()
        yield sessions, facility_id
    finally:
        async with sessions() as db:
            await db.execute(delete(jobs.AbdmJob).where(jobs.AbdmJob.facility_id == facility_id))
            await db.execute(
                delete(jobs.AbdmCallbackReply).where(
                    jobs.AbdmCallbackReply.facility_id == facility_id
                )
            )
            # Actual route mutations append immutable audit evidence. Preserve
            # its synthetic facility just as the audit suite does; never disable
            # the append-only trigger or delete those rows to tidy a test.
            has_audit = select(AuditLog.id).where(AuditLog.facility_id == facility_id).exists()
            await db.execute(delete(Facility).where(Facility.id == facility_id, ~has_audit))
            await db.commit()
        await engine.dispose()


@pytest.mark.parametrize("kind", ["hiu_consent", "hip_link_confirm"])
async def test_concurrent_callback_reply_reservation_is_atomic(pg_jobs, kind):
    sessions, facility_id = pg_jobs
    payload = HiuConsentNotifyCallback.model_validate(
        {
            "notification": {"consentRequestId": "TEST-CONSENT", "status": "GRANTED"},
        }
    )
    callback_id = str(uuid.uuid4())

    async def reserve():
        async with sessions() as db:
            ident = await callback_replies.schedule(
                db,
                facility_id=facility_id,
                kind=kind,
                gateway_request_id=callback_id,
                payload=payload,
                subject_ids=["TEST-ARTEFACT"],
            )
            await db.commit()
            return ident

    identifiers = await asyncio.wait_for(asyncio.gather(reserve(), reserve()), timeout=10)
    assert identifiers[0] == identifiers[1]
    async with sessions() as db:
        replies = (
            (
                await db.execute(
                    select(jobs.AbdmCallbackReply).where(
                        jobs.AbdmCallbackReply.facility_id == facility_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(replies) == 1
        assert (await db.get(jobs.AbdmJob, identifiers[0])).target_id == replies[0].id


async def test_concurrent_first_m2_init_creates_one_link_and_ack_job(pg_jobs, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.integrations.abdm import external_router
    from app.integrations.abdm.callback_auth import GatewayCallback
    from app.integrations.abdm.contracts_v3 import LinkInitCallback
    from app.integrations.abdm.hip import link_otp
    from app.integrations.abdm.hip.models import AbdmCareContextLink
    from app.patients.models import Patient
    from app.users.models import User

    sessions, facility_id = pg_jobs
    actor_id, patient_id = uuid.uuid4(), uuid.uuid4()
    transaction_id, event_id = str(uuid.uuid4()), str(uuid.uuid4())
    address = f"synthetic-{patient_id.hex}@sbx"
    monkeypatch.setattr(external_router, "_facility_id", AsyncMock(return_value=facility_id))
    # This test proves PostgreSQL first-insert serialization, not document validation.
    monkeypatch.setattr(
        external_router,
        "_contexts",
        AsyncMock(return_value=[SimpleNamespace(reference="synthetic/doc")]),
    )
    issue = AsyncMock(side_effect=AssertionError("No delivery before commit"))
    monkeypatch.setattr(link_otp, "ensure_issued", issue)
    try:
        async with sessions() as db:
            db.add(
                User(
                    id=actor_id,
                    username=f"m2-{actor_id.hex}",
                    keycloak_sub=str(actor_id),
                    full_name="Synthetic staff",
                    facility_id=facility_id,
                )
            )
            await db.flush()
            db.add(
                Patient(
                    id=patient_id,
                    uhid=f"SYN{patient_id.hex[:27]}",
                    facility_id=facility_id,
                    full_name="Synthetic participant",
                    sex="unknown",
                    age_years=30,
                    identity_path="demographics_only",
                    mobile="+919876543210",
                    abha_address=address,
                    created_by=actor_id,
                )
            )
            await db.commit()
        payload = LinkInitCallback.model_validate(
            {
                "transactionId": transaction_id,
                "abhaAddress": address,
                "patient": [
                    {
                        "referenceNumber": "synthetic",
                        "display": "Synthetic",
                        "hiType": "WellnessRecord",
                        "careContexts": [
                            {"referenceNumber": "synthetic/doc", "display": "Synthetic"}
                        ],
                    }
                ],
            }
        )
        callback = GatewayCallback(event_id, datetime.now(UTC), "TEST-HIP")

        async def initiate():
            async with sessions() as db:
                response = await external_router.link_init(payload, callback, db)
                await db.commit()
                return response.status_code

        assert await asyncio.wait_for(asyncio.gather(initiate(), initiate()), timeout=10) == [
            202,
            202,
        ]
        async with sessions() as db:
            links = list(
                (
                    await db.execute(
                        select(AbdmCareContextLink).where(
                            AbdmCareContextLink.facility_id == facility_id
                        )
                    )
                ).scalars()
            )
            assert len(links) == 1 and links[0].transaction_id == transaction_id
            replies = list(
                (
                    await db.execute(
                        select(jobs.AbdmCallbackReply).where(
                            jobs.AbdmCallbackReply.facility_id == facility_id
                        )
                    )
                ).scalars()
            )
            assert len(replies) == 1 and replies[0].target_id == links[0].id
            pending = list(
                (
                    await db.execute(
                        select(jobs.AbdmJob).where(jobs.AbdmJob.facility_id == facility_id)
                    )
                ).scalars()
            )
            assert len(pending) == 1 and pending[0].kind == "callback_ack"
        issue.assert_not_awaited()
    finally:
        async with sessions() as db:
            await db.execute(
                delete(AbdmCareContextLink).where(AbdmCareContextLink.facility_id == facility_id)
            )
            await db.execute(delete(Patient).where(Patient.id == patient_id))
            await db.execute(delete(User).where(User.id == actor_id))
            await db.commit()


async def test_callback_reply_and_job_rollback_together_on_postgres(pg_jobs):
    sessions, facility_id = pg_jobs
    payload = HiuConsentNotifyCallback.model_validate(
        {
            "notification": {"consentRequestId": "TEST-CONSENT", "status": "GRANTED"},
        }
    )
    async with sessions() as db:
        await callback_replies.schedule(
            db,
            facility_id=facility_id,
            kind="hiu_consent",
            gateway_request_id=str(uuid.uuid4()),
            payload=payload,
            subject_ids=["TEST-ARTEFACT"],
        )
        await db.rollback()
    async with sessions() as db:
        assert (
            await db.execute(
                select(jobs.AbdmCallbackReply).where(
                    jobs.AbdmCallbackReply.facility_id == facility_id
                )
            )
        ).scalars().all() == []
        assert (
            await db.execute(select(jobs.AbdmJob).where(jobs.AbdmJob.facility_id == facility_id))
        ).scalars().all() == []


async def test_parallel_enqueue_and_claim_have_exactly_one_owner(pg_jobs):
    sessions, facility_id = pg_jobs
    target_id = uuid.uuid4()

    async def enqueue():
        async with sessions() as db:
            ident = await jobs.enqueue(
                db, kind="hip_transfer", target_id=target_id, facility_id=facility_id
            )
            await db.commit()
            return ident

    identifiers = await asyncio.wait_for(asyncio.gather(enqueue(), enqueue()), timeout=10)
    assert identifiers[0] == identifiers[1]

    async def claim():
        async with sessions() as db:
            return await jobs.claim(db, ident=identifiers[0])

    results = await asyncio.wait_for(asyncio.gather(claim(), claim()), timeout=10)
    owners = [row for row in results if row is not None]
    assert len(owners) == 1
    assert owners[0].attempts == 1 and owners[0].status == "leased"
    async with sessions() as db:
        rows = (
            (await db.execute(select(jobs.AbdmJob).where(jobs.AbdmJob.facility_id == facility_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].lease_token == owners[0].lease_token


async def test_claim_skips_a_row_locked_by_another_transaction(pg_jobs):
    sessions, facility_id = pg_jobs
    async with sessions() as db:
        ident = await jobs.enqueue(
            db, kind="hip_transfer", target_id=uuid.uuid4(), facility_id=facility_id
        )
        await db.commit()
    async with sessions() as locked:
        await locked.execute(select(jobs.AbdmJob).where(jobs.AbdmJob.id == ident).with_for_update())
        async with sessions() as contender:
            assert await asyncio.wait_for(jobs.claim(contender, ident=ident), timeout=2) is None
        await locked.rollback()
    async with sessions() as db:
        assert (await jobs.claim(db, ident=ident)).id == ident


async def test_reclaimed_lease_fences_old_worker_finish_and_heartbeat(pg_jobs):
    sessions, facility_id = pg_jobs
    async with sessions() as db:
        ident = await jobs.enqueue(
            db, kind="hip_transfer", target_id=uuid.uuid4(), facility_id=facility_id
        )
        await db.commit()
        first = await jobs.claim(db, ident=ident)
    async with sessions() as db:
        replacement = await jobs.claim(
            db, ident=ident, now=datetime.now(UTC) + timedelta(minutes=3)
        )
    assert replacement.lease_token != first.lease_token
    async with sessions() as db:
        assert not await jobs.renew(db, first.id, first.lease_token)
        assert not await jobs.finish(db, first)
        row = await db.get(jobs.AbdmJob, ident)
        assert row.status == "leased" and row.lease_token == replacement.lease_token
        assert await jobs.finish(db, replacement)

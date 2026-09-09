"""Backfill contention and savepoint behavior on the deployed PostgreSQL schema."""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.audit.models import AuditLog
from app.integrations.abdm.hip import historical
from app.integrations.abdm.hip.models import AbdmCareContext
from app.integrations.abdm.jobs import AbdmJob
from app.opd.models import Encounter, Visit
from app.patients.models import Patient
from app.users.models import Facility, User
from tests.integrations.test_abdm_historical_documents import cli as cli_fixture

cli = cli_fixture


@pytest_asyncio.fixture
async def pg_historical():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL backfill tests")
    parsed = make_url(url)
    assert parsed.get_backend_name() == "postgresql"
    assert parsed.database and (
        parsed.database.endswith("_test") or parsed.database.startswith("test_")
    )
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    facility_id, operator_id, patient_id, visit_id = (uuid.uuid4() for _ in range(4))
    source_ids = [uuid.uuid4(), uuid.uuid4()]
    now = datetime.now(UTC)
    try:
        async with sessions() as db:
            db.add(
                Facility(
                    id=facility_id,
                    code=f"AH{uuid.uuid4().hex[:8]}",
                    name="Synthetic ABDM historical regression",
                    state_code="TS",
                )
            )
            await db.flush()
            db.add(
                User(
                    id=operator_id,
                    facility_id=facility_id,
                    username=f"ah-{uuid.uuid4().hex[:10]}",
                    keycloak_sub=str(uuid.uuid4()),
                    full_name="Synthetic Historical Operator",
                    registration_number="TEST-ONLY",
                )
            )
            await db.flush()
            db.add(
                Patient(
                    id=patient_id,
                    facility_id=facility_id,
                    uhid=f"AH{uuid.uuid4().hex[:12]}",
                    full_name="Synthetic Backfill Patient",
                    sex="unknown",
                    age_years=30,
                    identity_path="demographics_only",
                    created_by=operator_id,
                )
            )
            await db.flush()
            db.add(
                Visit(
                    id=visit_id,
                    patient_id=patient_id,
                    facility_id=facility_id,
                    visit_number=f"AH{uuid.uuid4().hex[:12]}",
                    visit_type="opd",
                    visit_date=now,
                    created_by=operator_id,
                )
            )
            await db.flush()
            for ident in source_ids:
                db.add(
                    Encounter(
                        id=ident,
                        visit_id=visit_id,
                        facility_id=facility_id,
                        provider_user_id=operator_id,
                        started_at=now - timedelta(hours=1),
                        ended_at=now,
                        created_by=operator_id,
                    )
                )
            await db.commit()
        yield (
            sessions,
            historical.HistoricalManifest(
                facility_id=facility_id,
                operator_id=operator_id,
                documents=[
                    {"patient_id": patient_id, "reference": f"encounter/{ident}"}
                    for ident in source_ids
                ],
            ),
        )
    finally:
        # Synthetic rows are deliberately retained only in the named test DB.
        # The append-only audit trigger must not be disabled to tidy a test.
        await engine.dispose()


async def test_postgres_cli_commit_failure_rolls_back_complete_batch(
    pg_historical, cli, monkeypatch
):
    sessions, manifest = pg_historical

    @asynccontextmanager
    async def failed_commit_session():
        async with sessions() as db:

            async def failed_commit():
                raise RuntimeError("Synthetic commit failure")

            monkeypatch.setattr(db, "commit", failed_commit)
            yield db

    monkeypatch.setattr(cli, "SessionLocal", failed_commit_session)
    with pytest.raises(RuntimeError, match="Synthetic"):
        await cli.execute(manifest, apply=True)
    async with sessions() as db:
        assert await scoped_count(db, AbdmCareContext, manifest.facility_id) == 0
        assert await scoped_count(db, AbdmJob, manifest.facility_id) == 0
        assert (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.facility_id == manifest.facility_id,
                    AuditLog.resource_type == "abdm_care_contexts",
                )
            )
        ).all() == []


async def scoped_count(db, model, facility_id):
    return await db.scalar(
        select(func.count())
        .select_from(model)
        .where(
            model.facility_id == facility_id,
        )
    )


async def test_concurrent_historical_apply_creates_each_context_once(pg_historical, monkeypatch):
    sessions, manifest = pg_historical
    first_inside, release_first, second_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    publish = historical.publish_document
    contender_pid = None
    calls = 0

    async def hold_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_inside.set()
            await asyncio.wait_for(release_first.wait(), timeout=15)
        return await publish(*args, **kwargs)

    monkeypatch.setattr(historical, "publish_document", hold_first)

    async def apply(*, contender=False):
        nonlocal contender_pid
        async with sessions() as db:
            if contender:
                contender_pid = await db.scalar(text("SELECT pg_backend_pid()"))
                second_started.set()
            results = await historical.register_historical_documents(db, manifest, apply=True)
            await db.commit()
            return [(r.status, r.context_id) for r in results]

    first = asyncio.create_task(apply())
    second = None
    try:
        await asyncio.wait_for(first_inside.wait(), timeout=10)
        second = asyncio.create_task(apply(contender=True))
        await asyncio.wait_for(second_started.wait(), timeout=10)

        async def observe_lock():
            async with sessions() as observer:
                while not await observer.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = :pid AND NOT granted)"),
                    {"pid": contender_pid},
                ):
                    if second.done():
                        raise AssertionError("Contender bypassed serialization")
                    await asyncio.sleep(0.02)

        # Observe an actual PostgreSQL wait, not just assume the tasks overlapped.
        await asyncio.wait_for(observe_lock(), timeout=10)
        release_first.set()
        created, existing = await asyncio.wait_for(asyncio.gather(first, second), timeout=10)
    finally:
        release_first.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(t for t in (first, second) if t is not None), return_exceptions=True)

    assert [status for status, _ in created] == ["created", "created"]
    assert [status for status, _ in existing] == ["existing", "existing"]
    assert [ident for _, ident in created] == [ident for _, ident in existing]
    assert calls == 2
    async with sessions() as db:
        assert await scoped_count(db, AbdmCareContext, manifest.facility_id) == 2
        assert await scoped_count(db, AbdmJob, manifest.facility_id) == 2
        audit = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.facility_id == manifest.facility_id,
                    AuditLog.resource_type == "abdm_care_contexts",
                )
            )
        ).all()
        assert len(audit) == 2
        assert all(a.user_id == manifest.operator_id for a in audit)


async def test_postgres_partial_failure_rolls_back_context_job_and_audit(
    pg_historical, monkeypatch
):
    sessions, manifest = pg_historical
    publish = historical.publish_document
    calls = 0

    async def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Synthetic late failure")
        return await publish(*args, **kwargs)

    monkeypatch.setattr(historical, "publish_document", fail_second)
    async with sessions() as db:
        with pytest.raises(RuntimeError, match="Synthetic"):
            await historical.register_historical_documents(db, manifest, apply=True)
        await db.commit()  # The service savepoint must already have undone the batch.
    assert calls == 2
    async with sessions() as db:
        assert await scoped_count(db, AbdmCareContext, manifest.facility_id) == 0
        assert await scoped_count(db, AbdmJob, manifest.facility_id) == 0
        assert (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.facility_id == manifest.facility_id,
                    AuditLog.resource_type == "abdm_care_contexts",
                )
            )
        ).all() == []

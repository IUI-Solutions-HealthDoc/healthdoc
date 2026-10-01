import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.integrations.abdm import job_runner, jobs
from app.users.models import Facility
from scripts import run_abdm_test_session as session


async def test_session_claim_excludes_old_other_facility_and_frozen_even_by_id(db, seed):
    department, _, _ = seed
    facility = department.facility_id
    other_facility = Facility(id=uuid.uuid4(), code="OTHER", name="Other facility", state_code="TS")
    db.add(other_facility)
    await db.flush()
    cutoff = datetime.now(UTC) - timedelta(minutes=1)
    ids = {}
    for key in ["old", "other", "frozen", "future", "new"]:
        ids[key] = await jobs.enqueue(
            db, kind="context_notify", target_id=uuid.uuid4(), facility_id=facility
        )
        row = await db.get(jobs.AbdmJob, ids[key])
        row.created_at = cutoff + timedelta(seconds=1)
        row.available_at = cutoff
        if key == "old":
            row.created_at = cutoff - timedelta(seconds=1)
        if key == "other":
            row.facility_id = other_facility.id
        if key == "frozen":
            row.status = "frozen"
        if key == "future":
            row.available_at = datetime.now(UTC) + timedelta(days=1)
    await db.commit()
    for key in ["old", "other", "frozen", "future"]:
        assert (
            await jobs.claim(db, ident=ids[key], facility_id=facility, created_since=cutoff) is None
        )
        assert (await db.get(jobs.AbdmJob, ids[key])).attempts == 0
    claimed = await jobs.claim(db, facility_id=facility, created_since=cutoff)
    assert claimed.id == ids["new"]
    assert claimed.attempts == 1
    assert await jobs.claim(db, facility_id=facility, created_since=cutoff) is None


async def test_cutoff_cannot_silently_dispatch_across_facilities_or_use_naive_time(db, seed):
    for options in [
        {"created_since": datetime.now(UTC)},
        {"facility_id": seed[0].facility_id, "created_since": datetime.now()},
    ]:
        with pytest.raises(ValueError, match="facility and timezone-aware"):
            await jobs.claim(db, **options)


async def test_scoped_runner_carries_filters_to_atomic_claim(monkeypatch, db, seed):
    claim = AsyncMock(return_value=None)
    monkeypatch.setattr(jobs, "claim", claim)
    cutoff = datetime.now(UTC)
    # Claim is mocked: opening the session does not acquire a real connection.
    assert not await job_runner.run_once(facility_id=seed[0].facility_id, created_since=cutoff)
    assert claim.call_args.kwargs == {
        "ident": None,
        "facility_id": seed[0].facility_id,
        "created_since": cutoff,
    }


async def test_wrong_gateway_or_sender_is_refused_before_database_or_dispatch(monkeypatch):
    from types import SimpleNamespace

    valid = dict(
        abdm_gateway_base_url="https://dev.abdm.gov.in",
        abdm_x_cm_id="sbx",
        abdm_hfr_facility_id="TEST",
        abdm_hip_id="TEST",
        abdm_hiu_id="TEST",
    )
    for change in [
        {"abdm_gateway_base_url": "https://production.example"},
        {"abdm_x_cm_id": "abdm"},
        {"abdm_hip_id": "OLD"},
        {"abdm_hiu_id": "OLD"},
    ]:
        monkeypatch.setattr(
            session, "get_settings", lambda change=change: SimpleNamespace(**(valid | change))
        )
        with pytest.raises(ValueError, match="Sandbox gateway"):
            await session.check_scope(uuid.uuid4(), "TEST")


async def test_dry_run_never_dispatches(monkeypatch, capsys):
    from types import SimpleNamespace

    context = AsyncMock()
    context.__aenter__.return_value.execute.return_value = SimpleNamespace(all=lambda: [])
    monkeypatch.setattr(session, "SessionLocal", lambda: context)
    monkeypatch.setattr(session, "check_scope", AsyncMock())
    dispatch = AsyncMock()
    monkeypatch.setattr(session, "run_once", dispatch)
    await session.run_session(
        facility_id=uuid.uuid4(), service_id="TEST", since=datetime.now(UTC), execute=False
    )
    dispatch.assert_not_awaited()
    assert "dry_run_no_dispatch" in capsys.readouterr().out

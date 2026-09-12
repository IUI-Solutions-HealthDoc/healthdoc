from unittest.mock import AsyncMock

import pytest

from app.integrations.abdm import job_runner


@pytest.mark.parametrize("once", [False, True])
async def test_cleanup_never_enters_outbound_consumer(monkeypatch, once):
    dispatch = AsyncMock(side_effect=AssertionError("must not send"))
    loop, cleanup = AsyncMock(), AsyncMock(return_value=3)
    monkeypatch.setattr(job_runner, "_poll_jobs", dispatch)
    monkeypatch.setattr(job_runner, "run_once", dispatch)
    monkeypatch.setattr(job_runner, "_poll_cleanup", loop)
    monkeypatch.setattr(job_runner, "cleanup_expired_keys", cleanup)
    await job_runner.run_mode(mode="cleanup", once=once)
    dispatch.assert_not_called()
    (cleanup if once else loop).assert_awaited_once()
    (loop if once else cleanup).assert_not_called()


async def test_cleanup_once_failure_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(
        job_runner, "cleanup_expired_keys", AsyncMock(side_effect=RuntimeError("test outage"))
    )
    with pytest.raises(RuntimeError, match="test outage"):
        await job_runner.run_mode(mode="cleanup", once=True)


async def test_once_cannot_dispatch_one_arbitrary_job():
    with pytest.raises(ValueError):
        await job_runner.run_mode(mode="all", once=True)

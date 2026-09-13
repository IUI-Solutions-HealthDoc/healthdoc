"""Exercise the actual proof-reservation Lua, not only its Python test double."""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from redis.asyncio import Redis

from app.integrations.abdm.hip import link_otp


async def test_actual_redis_reserves_only_same_proof_without_extending_expiry(monkeypatch):
    url = os.environ.get("REDIS_URL")
    if not os.environ.get("TEST_DATABASE_URL") or not url:
        pytest.skip("Explicit test infrastructure is required")
    # Dedicated logical test DB, unique key, no FLUSH/read of other keys.
    redis = Redis.from_url(url, db=15, decode_responses=True)
    ref = f"synthetic-m2-proof-{uuid.uuid4()}"
    key = f"abdm:link-otp:{ref}"
    monkeypatch.setattr(link_otp, "get_redis", lambda: redis)
    monkeypatch.setattr(link_otp, "_get_hmac_key", lambda: b"synthetic-proof-key" * 2)
    deliver = AsyncMock()
    monkeypatch.setattr(link_otp, "_deliver", deliver)
    try:
        await link_otp.issue(link_ref_number=ref, mobile="9876543210")
        code = deliver.call_args.kwargs["otp"]
        original_ttl = await redis.pttl(key)
        first = str(uuid.uuid4())
        for _ in range(2):
            await link_otp.verify(link_ref_number=ref, otp=code, confirmation_id=first)
        for supplied, callback in [
            (code, str(uuid.uuid4())), ("not-a-code", first), (code, "")
        ]:
            with pytest.raises(link_otp.LinkOtpExpired):
                await link_otp.verify(link_ref_number=ref, otp=supplied, confirmation_id=callback)
        state = json.loads(await redis.get(key))
        assert set(state) == {"digest", "attempts", "confirmation_id"}
        assert state["attempts"] == 0 and state["confirmation_id"] == first
        assert 0 < await redis.pttl(key) <= original_ttl
        # Deliberately expire only this test's key; no new proof or TTL may appear.
        await redis.pexpire(key, 0)
        with pytest.raises(link_otp.LinkOtpExpired):
            await link_otp.verify(link_ref_number=ref, otp=code, confirmation_id=first)
        assert not await redis.exists(key)
    finally:
        await redis.delete(key)
        await redis.aclose()


@pytest.mark.parametrize("outcome", ["accepted", "ambiguous"])
async def test_actual_delivery_guard_never_resends_or_replaces_otp(monkeypatch, outcome):
    url = os.environ.get("REDIS_URL")
    if not os.environ.get("TEST_DATABASE_URL") or not url:
        pytest.skip("Explicit test infrastructure is required")
    redis = Redis.from_url(url, db=15, decode_responses=True)
    ref = f"synthetic-m2-delivery-{uuid.uuid4()}"
    key, guard = f"abdm:link-otp:{ref}", f"abdm:link-otp:{ref}:delivery"
    monkeypatch.setattr(link_otp, "get_redis", lambda: redis)
    monkeypatch.setattr(link_otp, "_get_hmac_key", lambda: b"synthetic-proof-key" * 2)
    deliver = AsyncMock()
    if outcome == "ambiguous":
        deliver.side_effect = link_otp.LinkOtpUnavailable("synthetic relay timeout")
    monkeypatch.setattr(link_otp, "_deliver", deliver)
    args = dict(link_ref_number=ref, mobile="9876543210", expires_at=datetime.now(UTC) + timedelta(seconds=60))
    try:
        results = await asyncio.gather(
            link_otp.ensure_issued(**args), link_otp.ensure_issued(**args), return_exceptions=True,
        )
        deliver.assert_awaited_once()
        first_ttl = await redis.pttl(guard)
        if outcome == "accepted":
            assert "******3210" in results
            proof = json.loads(await redis.get(key))
            code = deliver.call_args.kwargs["otp"]
            assert set(proof) == {"digest", "attempts"} and proof["digest"] != code
            assert await link_otp.ensure_issued(**args) == "******3210"
            for _ in range(2):
                with pytest.raises(link_otp.LinkOtpInvalid):
                    await link_otp.verify(link_ref_number=ref, otp="not-a-code", confirmation_id="same-retry")
            assert json.loads(await redis.get(key))["attempts"] == 1
            await redis.delete(key)  # Consumed/locked proof must not regenerate.
        with pytest.raises(link_otp.LinkOtpUnavailable):
            await link_otp.ensure_issued(**args)
        deliver.assert_awaited_once()
        assert 0 < await redis.pttl(guard) <= first_ttl
        # Both keys disappearing cannot authorize a code beyond the DB deadline.
        await redis.delete(key, guard)
        args["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
        with pytest.raises(link_otp.LinkOtpUnavailable):
            await link_otp.ensure_issued(**args)
        deliver.assert_awaited_once()
    finally:
        await redis.delete(key, guard)
        await redis.aclose()

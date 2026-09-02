"""M2 mediated-linking OTPs are delivered, bounded, and never stored clear."""

from __future__ import annotations

import json

import pytest

from app.integrations.abdm.hip import link_otp


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key, value, *, ex=None, **kwargs):
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, key):
        self.values.pop(key, None)
        self.ttls.pop(key, None)

    async def eval(self, script, number_of_keys, key, presented, max_attempts):
        raw = self.values.get(key)
        if raw is None:
            return -1
        state = json.loads(raw)
        if state["attempts"] >= int(max_attempts):
            await self.delete(key)
            return -1
        if state["digest"] == presented:
            await self.delete(key)
            return 1
        state["attempts"] += 1
        if state["attempts"] >= int(max_attempts):
            await self.delete(key)
            return -1
        self.values[key] = json.dumps(state)
        return 0


@pytest.fixture
def redis(monkeypatch):
    fake = _Redis()
    monkeypatch.setattr(link_otp, "get_redis", lambda: fake)
    monkeypatch.setattr(link_otp, "_get_hmac_key", lambda: b"k" * 32)
    monkeypatch.setattr(link_otp.secrets, "randbelow", lambda _: 123456)
    return fake


async def test_issue_stores_only_a_ttl_bound_digest_and_delivers(monkeypatch, redis):
    delivered = {}

    async def _deliver(**kwargs):
        delivered.update(kwargs)

    monkeypatch.setattr(link_otp, "_deliver", _deliver)

    hint = await link_otp.issue(link_ref_number="LINK-1", mobile="+91 98765 43210")

    stored = redis.values["abdm:link-otp:LINK-1"]
    assert "123456" not in stored
    assert redis.ttls["abdm:link-otp:LINK-1"] == link_otp.OTP_TTL_SECONDS
    assert delivered == {"mobile": "+91 98765 43210", "otp": "123456"}
    assert hint == "******3210"


async def test_correct_code_is_single_use(monkeypatch, redis):
    async def _delivered(**kwargs):
        return None

    monkeypatch.setattr(link_otp, "_deliver", _delivered)
    await link_otp.issue(link_ref_number="LINK-1", mobile="9876543210")

    await link_otp.verify(link_ref_number="LINK-1", otp="123456")
    with pytest.raises(link_otp.LinkOtpExpired):
        await link_otp.verify(link_ref_number="LINK-1", otp="123456")


async def test_wrong_codes_are_bounded_and_lock_the_session(monkeypatch, redis):
    async def _delivered(**kwargs):
        return None

    monkeypatch.setattr(link_otp, "_deliver", _delivered)
    await link_otp.issue(link_ref_number="LINK-1", mobile="9876543210")

    for _ in range(link_otp.MAX_ATTEMPTS - 1):
        with pytest.raises(link_otp.LinkOtpInvalid):
            await link_otp.verify(link_ref_number="LINK-1", otp="000000")
    with pytest.raises(link_otp.LinkOtpExpired):
        await link_otp.verify(link_ref_number="LINK-1", otp="000000")
    assert "abdm:link-otp:LINK-1" not in redis.values


async def test_failed_delivery_removes_the_pending_digest(monkeypatch, redis):
    async def _failed(**kwargs):
        raise link_otp.LinkOtpUnavailable("relay down")

    monkeypatch.setattr(link_otp, "_deliver", _failed)
    with pytest.raises(link_otp.LinkOtpUnavailable):
        await link_otp.issue(link_ref_number="LINK-1", mobile="9876543210")
    assert redis.values == {}


@pytest.mark.parametrize("mobile", ["", "123", "+not-a-number"])
async def test_missing_or_invalid_mobile_is_refused_before_storage(redis, mobile):
    with pytest.raises(link_otp.LinkOtpUnavailable):
        await link_otp.issue(link_ref_number="LINK-1", mobile=mobile)
    assert redis.values == {}

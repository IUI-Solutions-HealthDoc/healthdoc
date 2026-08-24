"""Redis cache behaviour and facility-capability invalidation."""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from redis.exceptions import RedisError

from app.common import cache, modules
from app.common import facility_modules as fm


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, int]] = []
        self.deleted: list[str] = []
        self.fail = False

    async def get(self, key: str) -> str | None:
        if self.fail:
            raise RedisError("offline")
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        if self.fail:
            raise RedisError("offline")
        self.values[key] = value
        self.set_calls.append((key, ex))

    async def delete(self, key: str) -> None:
        if self.fail:
            raise RedisError("offline")
        self.deleted.append(key)
        self.values.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch) -> FakeRedis:
    redis = FakeRedis()
    monkeypatch.setattr(cache, "get_redis", lambda: redis)
    return redis


async def test_json_cache_round_trip_and_ttl(fake_redis) -> None:
    await cache.set_json("capabilities", "facility-a", {"lab": False}, ttl=300)

    assert await cache.get_json("capabilities", "facility-a") == {"lab": False}
    assert fake_redis.set_calls == [
        (cache.cache_key("capabilities", "facility-a"), 300)
    ]


async def test_cache_is_fail_open(fake_redis) -> None:
    fake_redis.fail = True

    assert await cache.get_json("capabilities", "facility-a") is None
    await cache.set_json("capabilities", "facility-a", {}, ttl=30)
    await cache.invalidate("capabilities", "facility-a")


async def test_capabilities_cache_hit_skips_postgres(fake_redis) -> None:
    facility_id = uuid.uuid4()
    expected = {code: True for code in modules.ModuleCode.values()}
    fake_redis.values[cache.cache_key("facility-capabilities", str(facility_id))] = json.dumps(
        expected
    )

    class DbMustNotRun:
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("cache hit queried PostgreSQL")

    assert await modules.get_capabilities(DbMustNotRun(), facility_id) == expected


async def test_module_mutation_invalidates_after_commit(fake_redis) -> None:
    facility_id = uuid.uuid4()
    # Existing facility-module tests prove the database upsert.  Keep this
    # unit test focused on the ordering of mutation and invalidation.
    events: list[str] = []

    class Row:
        def __init__(self) -> None:
            self.id = uuid.uuid4()
            self.facility_id = facility_id
            self.module_code = "lab"
            self.is_enabled = True
            self.config = {}
            self.enabled_at = self.disabled_at = self.disabled_reason = None

    class Result:
        def scalar_one_or_none(self):
            return Row()

    class FakeDb:
        async def execute(self, *_args, **_kwargs):
            return Result()

        async def flush(self):
            events.append("flush")

        async def commit(self):
            events.append("commit")

        async def refresh(self, _row):
            events.append("refresh")

    original_delete = fake_redis.delete

    async def recording_delete(key: str) -> None:
        events.append("invalidate")
        await original_delete(key)

    fake_redis.delete = recording_delete
    result = await fm.update_facility_module(
        "lab", fm.FacilityModuleUpdate(is_enabled=False, disabled_reason="maintenance"),
        SimpleNamespace(facility_id=facility_id), db=FakeDb(),
    )

    assert result.is_enabled is False
    assert events == ["flush", "commit", "refresh", "invalidate"]

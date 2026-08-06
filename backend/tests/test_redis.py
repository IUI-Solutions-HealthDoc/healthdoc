"""Tests for app/common/redis.py — pub/sub connection module (B4-W1-02)."""
import asyncio
import json

import pytest

from app.common.redis import (
    close_redis,
    get_redis,
    publish,
    publish_event,
    queue_channel,
    subscribe,
)


@pytest.fixture(autouse=True)
async def _cleanup_redis():
    """Ensure every test starts and ends with a fresh pooled connection."""
    yield
    await close_redis()


def test_queue_channel_naming():
    assert queue_channel("dept-123") == "queue:dept-123"


@pytest.mark.asyncio
async def test_get_redis_returns_same_pooled_instance():
    client_a = get_redis()
    client_b = get_redis()
    assert client_a is client_b


@pytest.mark.asyncio
async def test_redis_connection_ping():
    redis = get_redis()
    pong = await redis.ping()
    assert pong is True


@pytest.mark.asyncio
async def test_publish_and_subscribe_raw_message():
    channel = "test:raw"
    async with subscribe(channel) as pubsub:
        await asyncio.sleep(0.1)  # let the subscription register before publishing

        await publish(channel, "hello")

        msg = await asyncio.wait_for(_first_message(pubsub), timeout=2)
        assert msg["data"] == "hello"


@pytest.mark.asyncio
async def test_publish_event_shape():
    department_id = "test-dept"
    channel = queue_channel(department_id)
    async with subscribe(channel) as pubsub:
        await asyncio.sleep(0.1)

        payload = {"queue_id": "Q1", "doctor_name": "Dr. A"}
        await publish_event(channel, "token_called", payload)

        msg = await asyncio.wait_for(_first_message(pubsub), timeout=2)
        event = json.loads(msg["data"])
        assert event["event_type"] == "token_called"
        assert event["payload"] == payload


@pytest.mark.asyncio
async def test_publish_raises_on_redis_error(monkeypatch):
    """publish() must re-raise RedisError, never swallow it silently."""
    from redis.exceptions import RedisError

    client = get_redis()

    async def _broken_publish(*args, **kwargs):
        raise RedisError("simulated outage")

    monkeypatch.setattr(client, "publish", _broken_publish)

    with pytest.raises(RedisError):
        await publish("test:broken", "x")


@pytest.mark.asyncio
async def test_subscribe_raises_on_redis_error(monkeypatch):
    """subscribe() must re-raise RedisError, never return None on failure."""
    from redis.exceptions import RedisError

    client = get_redis()

    def _broken_pubsub():
        raise RedisError("simulated outage")

    monkeypatch.setattr(client, "pubsub", _broken_pubsub)

    with pytest.raises(RedisError):
        async with subscribe("test:broken"):
            pass

async def _first_message(pubsub):
    """Skip the subscribe-confirmation message; return the first real one."""
    async for msg in pubsub.listen():
        if msg["type"] == "message":
            return msg
        

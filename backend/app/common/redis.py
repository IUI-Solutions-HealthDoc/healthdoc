"""Redis connection (queue tokens, pub/sub for live displays).

B4-W1-02 extends this with the pub/sub helper for queue-display websockets.
"""
import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.common.config import get_settings

logger = logging.getLogger(__name__)

#: One pool per event loop, keyed by the loop itself.
#:
#: This was a single module-level pool. An asyncio Redis client binds its
#: connections to the loop that created them, so the first loop to call
#: get_redis() owned the pool forever — and any *other* loop that reused it got
#: "Future attached to a different loop", then "Event loop is closed" once the
#: original had finished.
#:
#: In production there is one loop per worker process, so this never showed. It
#: showed the moment the SSE tests booted uvicorn on its own loop alongside
#: pytest's: the queue display stream died on subscribe, and the client saw an
#: empty 200 rather than an error.
_pools: dict[object, aioredis.Redis] = {}

_NO_LOOP = object()


def _loop_key() -> object:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return _NO_LOOP


def get_redis() -> aioredis.Redis:
    """Return a pooled Redis connection for the calling event loop."""
    key = _loop_key()
    pool = _pools.get(key)
    if pool is None:
        pool = aioredis.from_url(
            get_settings().redis_url, decode_responses=True, health_check_interval=30
        )
        _pools[key] = pool
    return pool


async def close_redis() -> None:
    """Close this loop's pooled connection. Call from FastAPI's lifespan on shutdown."""
    pool = _pools.pop(_loop_key(), None)
    if pool is not None:
        await pool.aclose()


def queue_channel(department_id: str | uuid.UUID) -> str:
    """Channel name for a department's queue display board."""
    return f"queue:{department_id}"


def stock_alert_channel(facility_id: str | uuid.UUID) -> str:
    """Channel name for a facility's stock alert SSE stream."""
    return f"stock_alerts:{facility_id}"
  
def department_channel(department_id: str | uuid.UUID) -> str:
    """Generic department-scoped channel for staff alerts."""
    return f"dept:{department_id}"


def facility_channel(facility_id: str | uuid.UUID) -> str:
    """Generic facility-wide channel for staff alerts.

    Distinct from stock_alert_channel above: that one is the pharmacy's
    low-stock stream, this is the general facility-wide staff channel the
    notifications module publishes to. Both exist on purpose.
    """
    return f"facility:{facility_id}"
  
async def publish(channel: str, message: str) -> None:
    """Publish a raw string message to a channel."""
    try:
        redis = get_redis()
        await redis.publish(channel, message)
        logger.info("Published raw message to channel=%s", channel)
    except RedisError:
        logger.error("Redis publish failed for channel=%s", channel, exc_info=True)
        raise


async def publish_event(channel: str, event_type: str, payload: dict) -> None:
    """Publish a structured JSON event: {"event_type": ..., "payload": {...}}."""
    event = {"event_type": event_type, "payload": payload}
    try:
        await publish(channel, json.dumps(event))
    except Exception:
        logger.error(
            "publish_event failed for channel=%s event_type=%s -- swallowed, "
            "notification_history already has the durable record",
            channel, event_type, exc_info=True,
        )

@asynccontextmanager
async def subscribe(channel: str):
    """Subscribe to a channel as an async context manager -- guarantees
    the subscription is cleaned up even if the caller disconnects or
    raises partway through:
 
        async with subscribe(channel) as pubsub:
            async for message in pubsub.listen():
                ...
    """
    redis = get_redis()
    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe(channel)
        logger.info("Subscribed to channel=%s", channel)
        yield pubsub
    except RedisError:
        logger.error("Redis subscribe failed for channel=%s", channel, exc_info=True)
        raise
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        logger.info("Unsubscribed from channel=%s", channel)
        

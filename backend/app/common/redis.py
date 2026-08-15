"""Redis connection (queue tokens, pub/sub for live displays).

B4-W1-02 extends this with the pub/sub helper for queue-display websockets.
"""
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Union

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.common.config import get_settings

logger = logging.getLogger(__name__)

_pool: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return a pooled Redis connection."""
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(get_settings().redis_url, decode_responses=True, health_check_interval=30)
    return _pool

async def close_redis() -> None:
    """Close the pooled connection. Call from FastAPI's lifespan on shutdown."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


def queue_channel(department_id: Union[str, uuid.UUID]) -> str:
    """Channel name for a department's queue display board."""
    return f"queue:{department_id}"


def department_channel(department_id: Union[str, uuid.UUID]) -> str:
    """Generic department-scoped channel for staff alerts."""
    return f"dept:{department_id}"
 
 
def facility_channel(facility_id: Union[str, uuid.UUID]) -> str:
    """Generic facility-wide channel for staff alerts."""
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
        

"""Small, fail-open Redis cache for read-mostly application data.

Redis is an optimisation here, never the source of truth.  A cache outage or
an old/corrupt value therefore falls back to PostgreSQL instead of making a
clinical endpoint unavailable.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from redis.exceptions import RedisError

from app.common.redis import get_redis

logger = logging.getLogger(__name__)

_VERSION = "v1"


def cache_key(namespace: str, identity: str) -> str:
    return f"healthdoc:{_VERSION}:{namespace}:{identity}"


async def get_json(namespace: str, identity: str) -> Any | None:
    """Return decoded JSON, or ``None`` on miss/cache failure."""
    key = cache_key(namespace, identity)
    try:
        raw = await get_redis().get(key)
        return json.loads(raw) if raw is not None else None
    except (RedisError, TypeError, ValueError):
        logger.warning("Redis cache read failed for key=%s", key, exc_info=True)
        return None


async def set_json(namespace: str, identity: str, value: Any, *, ttl: int) -> None:
    """Store JSON for ``ttl`` seconds; silently degrade if Redis is down."""
    key = cache_key(namespace, identity)
    try:
        await get_redis().set(key, json.dumps(value), ex=ttl)
    except (RedisError, TypeError, ValueError):
        logger.warning("Redis cache write failed for key=%s", key, exc_info=True)


async def invalidate(namespace: str, identity: str) -> None:
    """Remove one cached value; a Redis outage must not fail the mutation."""
    key = cache_key(namespace, identity)
    try:
        await get_redis().delete(key)
    except RedisError:
        logger.warning("Redis cache invalidation failed for key=%s", key, exc_info=True)

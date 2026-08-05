"""Redis caching helper (B1-W7-02, performance).

Small decorator + helpers for caching hot, read-mostly lookups (facility capabilities,
department lists, ICD searches) to cut N+1 pressure on Postgres. Cache is advisory:
always safe to miss; invalidate on write.
"""
import functools
import hashlib
import json
from typing import Any, Awaitable, Callable

from app.common.redis import get_redis

DEFAULT_TTL = 300  # seconds


def _key(prefix: str, *parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return f"cache:{prefix}:{hashlib.sha1(raw.encode()).hexdigest()[:16]}"


def cached(prefix: str, ttl: int = DEFAULT_TTL):
    """Cache the JSON-serialisable return of an async function."""
    def deco(fn: Callable[..., Awaitable[Any]]):
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            r = get_redis()
            key = _key(prefix, args[1:], kwargs)  # skip self/db arg 0
            hit = await r.get(key)
            if hit is not None:
                return json.loads(hit)
            val = await fn(*args, **kwargs)
            await r.set(key, json.dumps(val, default=str), ex=ttl)
            return val
        return wrapper
    return deco


async def invalidate(prefix: str) -> int:
    """Drop every key under a prefix (call on writes to that domain)."""
    r = get_redis()
    n = 0
    async for k in r.scan_iter(match=f"cache:{prefix}:*"):
        await r.delete(k)
        n += 1
    return n

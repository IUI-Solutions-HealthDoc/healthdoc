"""
backend/app/common/idempotency.py

Shared idempotency-key handling per schema §4A.1.

Table (migration 0033): idempotency_keys
    key              varchar(64)
    endpoint         varchar(120)
    request_hash     char(64)
    response_status  int
    response_body    jsonb
    user_id          UUID NULL -> users
    created_at       timestamptz
    UNIQUE (key, endpoint)

Behaviour (binding, from §4A.1):
    - First call executes and stores the response.
    - A repeat with the same key replays the stored response -- never
      re-executes.
    - Same key + different body => 409 idempotency_key_reuse.
    - Keys expire after 24h (see purge_expired_idempotency_keys).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.models import IdempotencyKey


@dataclass
class CachedResponse:
    response_status: int
    response_body: Any


def _hash_body(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


async def consume_idempotency_key(
    db: AsyncSession,
    *,
    key: str,
    endpoint: str,
    request_body: bytes,
    user_id: UUID | None,
) -> CachedResponse | None:
    if len(key) > 64:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_idempotency_key", "message": "Idempotency-Key exceeds 64 chars"},
        )

    request_hash = _hash_body(request_body)

    result = await db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.key == key,
            IdempotencyKey.endpoint == endpoint,
        )
    )
    row = result.scalar_one_or_none()

    if row is None:
        return None

    if row.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "idempotency_key_reuse",
                "message": "This Idempotency-Key was already used with a different request body",
            },
        )

    return CachedResponse(
        response_status=row.response_status,
        response_body=row.response_body,
    )


async def store_idempotency_response(
    db: AsyncSession,
    *,
    key: str,
    endpoint: str,
    request_body: bytes,
    response_status: int,
    response_body: Any,
    user_id: UUID | None,
) -> None:
    request_hash = _hash_body(request_body)

    stmt = (
        pg_insert(IdempotencyKey)
        .values(
            key=key,
            endpoint=endpoint,
            request_hash=request_hash,
            response_status=response_status,
            response_body=response_body,
            user_id=user_id,
        )
        .on_conflict_do_nothing(index_elements=["key", "endpoint"])
    )
    await db.execute(stmt)


async def purge_expired_idempotency_keys(db: AsyncSession) -> int:
    """24h expiry sweep. Run as a scheduled job, not from a request path."""
    result = await db.execute(
        delete(IdempotencyKey).where(
            IdempotencyKey.created_at < func.now() - timedelta(hours=24)
        )
    )
    await db.commit()
    return result.rowcount or 0

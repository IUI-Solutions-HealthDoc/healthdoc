"""Idempotency-Key handling (schema doc §4A.1).

The problem this solves: a receptionist's connection hiccups mid-request
and their browser silently retries. Without this, that retry creates a
SECOND token for the same patient. The fix: the client sends a
self-generated Idempotency-Key header with every creation request. The
first time a key is seen, the request runs normally and its result is
saved. Every later request with the SAME key gets the SAVED result
handed back -- the real logic never runs twice.

Usage pattern in a router:
    request_hash = hash_request_body(payload)
    existing = await check_idempotency(db, key, "POST /queue/tokens", request_hash, user_id)
    if existing is not None:
        return existing.response_body   # replay, don't re-run anything
    # ... do the real work ...
    await record_idempotent_response(db, key, "POST /queue/tokens", 201, response_body, user_id)
"""
import hashlib
import uuid

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.idempotency_models import IdempotencyKey


def hash_request_body(payload: BaseModel) -> str:
    """A stable fingerprint of the request body. Used to detect "same key,
    different body" -- reusing a key for a genuinely different request is
    a client bug, not something to silently allow."""
    return hashlib.sha256(payload.model_dump_json().encode()).hexdigest()


async def check_idempotency(
    db: AsyncSession,
    key: str,
    endpoint: str,
    request_hash: str,
    user_id: uuid.UUID | None,
) -> IdempotencyKey | None:
    """Returns the existing record if this exact request already ran --
    the caller should return existing.response_body as-is and do nothing
    else. Returns None if this is genuinely new -- the caller should
    proceed normally, then call record_idempotent_response() afterward.
    """
    existing = (
        await db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.key == key,
                IdempotencyKey.endpoint == endpoint,
                IdempotencyKey.user_id == user_id,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        # First time seeing this key for this endpoint -- reserve it now,
        # before doing any real work, so a second near-simultaneous
        # request with the same key sees this reservation instead of
        # also thinking it's the first.
        row = IdempotencyKey(
            id=uuid.uuid4(), key=key, endpoint=endpoint, request_hash=request_hash, user_id=user_id,
        )
        db.add(row)
        try:
            await db.flush()
            return None  # genuinely new -- caller proceeds
        except IntegrityError:
            # Race: another request reserved this exact key microseconds
            # ago. Fall through and treat it the same as "already exists".
            await db.rollback()
            existing = (
                await db.execute(
                    select(IdempotencyKey).where(
                IdempotencyKey.key == key,
                IdempotencyKey.endpoint == endpoint,
                IdempotencyKey.user_id == user_id,
            )
                )
            ).scalar_one()

    if existing.request_hash != request_hash:
        raise HTTPException(409, {
            "code": "idempotency_key_reuse",
            "message": "This Idempotency-Key was already used with a different request body",
        })

    if existing.response_status is None:
        # Reserved but never completed -- either another request is
        # mid-flight right now, or a previous attempt crashed before
        # finishing. Either way, the safe answer is "try again shortly",
        # not "silently proceed and maybe double-create something".
        raise HTTPException(409, {
            "code": "idempotency_key_in_progress",
            "message": "A request with this Idempotency-Key is already being processed",
        })

    return existing


async def record_idempotent_response(
    db: AsyncSession, key: str, endpoint: str, response_status: int, response_body: dict,
    user_id: uuid.UUID | None = None,
) -> None:
    """user_id must be the same one passed to check_idempotency — the row is
    keyed on (key, user_id, endpoint), so omitting it here would fail to find
    the reservation this call is meant to complete."""
    row = (
        await db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.key == key,
                IdempotencyKey.endpoint == endpoint,
                IdempotencyKey.user_id == user_id,
            )
        )
    ).scalar_one()
    row.response_status = response_status
    row.response_body = response_body
    await db.flush()

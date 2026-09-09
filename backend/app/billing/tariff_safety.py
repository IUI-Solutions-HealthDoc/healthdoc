"""Transaction-bound serialization and replay for tariff maintenance only.

Lock order: actor/action key, then facility/code/scheme. A row lock cannot
protect the first tariff because no row exists yet; NULL general schemes also
do not collide under the legacy unique constraint. No session/process lock or
separate commit can protect this boundary across workers.
"""
import hashlib
import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.idempotency import check_idempotency
from app.common.idempotency_models import IdempotencyKey


async def _lock(db: AsyncSession, parts: list[str | None]) -> None:
    # Match the existing PostgreSQL advisory-lock convention. A hash collision
    # can only serialize unrelated work, never grant access or skip a check.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": json.dumps(["healthdoc-tariff", *parts], separators=(",", ":"))},
    )


async def lock_tariff_family(
    db: AsyncSession, facility_id: uuid.UUID, charge_code: str, scheme_code: str | None,
) -> None:
    await _lock(db, ["family", str(facility_id), charge_code, scheme_code])


async def reserve_tariff_write(
    db: AsyncSession, *, key: str, endpoint: str, actor_id: uuid.UUID,
    facility_id: uuid.UUID, body: dict,
) -> IdempotencyKey | None:
    # The facility belongs in the fingerprint, not the lock/key namespace:
    # moving an account to another facility must not replay its former data.
    await _lock(db, ["action", str(actor_id), endpoint, key])
    digest = hashlib.sha256(json.dumps(
        {"facility_id": str(facility_id), "body": body}, sort_keys=True,
    ).encode()).hexdigest()
    return await check_idempotency(db, key, endpoint, digest, actor_id)

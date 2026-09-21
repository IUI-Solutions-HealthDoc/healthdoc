"""Atomic retry receipts for clinical writes; no service may commit inside write()."""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, TypeVar

from fastapi import Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.auth.deps import DbUser
from app.common.idempotency_models import IdempotencyKey
from app.common.patient_scope import actor_facility

ClinicalWriteKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]
Result = TypeVar("Result", bound=BaseModel)


async def clinical_write(
    db: AsyncSession, key: str, endpoint: str, payload: BaseModel, actor: DbUser,
    response_model: type[Result], write: Callable[[], Awaitable[Result]], *, status: int = 201,
) -> Result:
    """Call only AFTER current resource authorization, including on replays.

    INSERT ON CONFLICT waits for an uncommitted competing reservation in Postgres.
    It does not roll back the caller's transaction as a caught unique violation
    would. The domain write and receipt commit together, before reporting success.
    Facility participates in the fingerprint so a transferred staff account cannot
    replay a former facility's response. This does not change old endpoint hashes.
    """
    if "patient" in actor.roles:
        raise HTTPException(403, "A staff-only clinical session is required")
    facility_id = await actor_facility(db, actor.id)
    if facility_id != actor.facility_id:
        raise HTTPException(403, "Active facility context required")
    fingerprint = hashlib.sha256(json.dumps(
        {"facility_id": str(facility_id), "body": payload.model_dump(mode="json")},
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()
    dialect = db.get_bind().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
    if insert is None:
        raise RuntimeError("Clinical retry receipts require PostgreSQL (SQLite only for unit tests)")
    try:
        reserved_id = (await db.execute(
            insert(IdempotencyKey).values(
                id=uuid.uuid4(), key=key, endpoint=endpoint, user_id=actor.id,
                request_hash=fingerprint,
            ).on_conflict_do_nothing(index_elements=["key", "user_id", "endpoint"])
            .returning(IdempotencyKey.id)
        )).scalar_one_or_none()
        receipt = (await db.execute(select(IdempotencyKey).where(
            IdempotencyKey.key == key, IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.user_id == actor.id,
        ).execution_options(populate_existing=True))).scalar_one()
        if reserved_id is None:
            if receipt.request_hash != fingerprint:
                raise HTTPException(409, {"code": "idempotency_key_reuse",
                    "message": "This request key belongs to a different action or facility"})
            if receipt.response_status is None or receipt.response_body is None:
                raise HTTPException(409, {"code": "idempotency_key_in_progress",
                    "message": "The original write is not yet confirmed; retry unchanged"})
            return response_model.model_validate(receipt.response_body)
        result = response_model.model_validate(await write())
        receipt.response_status = status
        receipt.response_body = result.model_dump(mode="json")
        await db.flush()
        await db.commit()
        return result
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, {
            "code": "clinical_write_rejected",
            "message": "The record conflicts with current data. Refresh and review before saving again.",
        }) from exc
    except Exception:
        await db.rollback()
        raise

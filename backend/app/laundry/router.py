"""Laundry: linen collected from wards, washed, and counted back.

Ward staff and the services supervisor collect and track batches; the counts
on return show what was condemned and what went missing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import Bed, Ward
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.laundry import service
from app.laundry.models import LINEN_BATCH_STATUSES, LINEN_ITEM_TYPES, LinenBatch, LinenBatchEvent
from app.users.models import User

_STAFF = ("nurse", "admin", "hod", "supervisor")

router = APIRouter(prefix="/laundry", tags=["laundry"], dependencies=[Depends(require_roles(*_STAFF))])

ItemType = Literal[LINEN_ITEM_TYPES]  # type: ignore[valid-type]
BatchStatus = Literal[LINEN_BATCH_STATUSES]  # type: ignore[valid-type]


async def _idempotency_key(idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> str:
    if not idempotency_key:
        raise HTTPException(400, {"code": "missing_idempotency_key", "message": "Idempotency-Key header is required"})
    return idempotency_key


def _refused(exc: service.LaundryError) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "message": exc.message})


class LinenLine(BaseModel):
    item_type: ItemType
    quantity: int = Field(ge=1, le=1000)


class BatchCreate(BaseModel):
    ward_id: uuid.UUID | None = None
    bed_id: uuid.UUID | None = None
    source: str | None = Field(default=None, max_length=120)
    is_infected: bool = False
    notes: str | None = Field(default=None, max_length=500)
    items: list[LinenLine] = Field(min_length=1, max_length=len(LINEN_ITEM_TYPES))


class ReturnCount(BaseModel):
    item_type: ItemType
    returned: int = Field(ge=0, le=1000)
    condemned: int = Field(default=0, ge=0, le=1000)


class BatchAdvance(BaseModel):
    status: Literal["washing", "ready", "returned"]
    notes: str | None = Field(default=None, max_length=500)
    counts: list[ReturnCount] | None = None


class LineOut(BaseModel):
    item_type: str
    quantity: int
    returned_quantity: int | None
    condemned_quantity: int
    missing_quantity: int | None


class BatchEventOut(BaseModel):
    from_status: str | None
    to_status: str
    notes: str | None
    changed_by: str
    changed_at: datetime


class BatchOut(BaseModel):
    id: uuid.UUID
    ward_id: uuid.UUID | None
    ward_name: str | None
    bed_number: str | None
    source: str | None
    is_infected: bool
    status: str
    notes: str | None
    collected_at: datetime
    returned_at: datetime | None
    items: list[LineOut]


async def _out(db: AsyncSession, batch: LinenBatch) -> BatchOut:
    ward = await db.get(Ward, batch.ward_id) if batch.ward_id else None
    bed = await db.get(Bed, batch.bed_id) if batch.bed_id else None
    lines = await service.items_of(db, batch.id)
    return BatchOut(
        id=batch.id, ward_id=batch.ward_id, ward_name=ward.name if ward else None,
        bed_number=bed.bed_number if bed else None, source=batch.source, is_infected=batch.is_infected,
        status=batch.status, notes=batch.notes, collected_at=batch.collected_at, returned_at=batch.returned_at,
        items=[
            LineOut(
                item_type=line.item_type, quantity=line.quantity, returned_quantity=line.returned_quantity,
                condemned_quantity=line.condemned_quantity,
                missing_quantity=None if line.returned_quantity is None
                else line.quantity - line.returned_quantity - line.condemned_quantity,
            )
            for line in lines
        ],
    )


@router.get("/batches", response_model=list[BatchOut])
async def list_batches(
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    status: BatchStatus | None = Query(None),
    open_only: bool = Query(False),
) -> list[BatchOut]:
    stmt = select(LinenBatch).where(LinenBatch.facility_id == current_db_user.facility_id)
    if status:
        stmt = stmt.where(LinenBatch.status == status)
    elif open_only:
        stmt = stmt.where(LinenBatch.status != "returned")
    rows = (await db.execute(stmt.order_by(LinenBatch.collected_at.desc()).limit(200))).scalars().all()
    return [await _out(db, row) for row in rows]


@router.post("/batches", status_code=201, response_model=BatchOut)
async def collect_linen(
    payload: BatchCreate,
    current_db_user: CurrentDbUser,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    db: AsyncSession = Depends(get_db),
) -> BatchOut:
    endpoint, request_hash = "POST /laundry/batches", hash_request_body(payload)
    cached = await check_idempotency(db, idempotency_key, endpoint, request_hash, current_db_user.id)
    if cached is not None:
        return BatchOut.model_validate(cached.response_body)
    try:
        batch = await service.collect(
            db, facility_id=current_db_user.facility_id, user_id=current_db_user.id,
            items=[(line.item_type, line.quantity) for line in payload.items], ward_id=payload.ward_id,
            bed_id=payload.bed_id, source=payload.source, is_infected=payload.is_infected, notes=payload.notes,
        )
    except service.LaundryError as exc:
        raise _refused(exc) from None
    out = await _out(db, batch)
    await record_idempotent_response(db, idempotency_key, endpoint, 201, out.model_dump(mode="json"), current_db_user.id)
    return out


@router.post("/batches/{batch_id}/status", response_model=BatchOut)
async def advance_batch(
    batch_id: uuid.UUID,
    payload: BatchAdvance,
    current_db_user: CurrentDbUser,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    db: AsyncSession = Depends(get_db),
) -> BatchOut:
    endpoint, request_hash = f"POST /laundry/batches/{batch_id}/status", hash_request_body(payload)
    cached = await check_idempotency(db, idempotency_key, endpoint, request_hash, current_db_user.id)
    if cached is not None:
        return BatchOut.model_validate(cached.response_body)
    try:
        batch = await service.get_scoped(db, batch_id, current_db_user.facility_id, lock=True)
        counts = {c.item_type: (c.returned, c.condemned) for c in payload.counts or []}
        await service.advance(
            db, batch, to_status=payload.status, user_id=current_db_user.id, notes=payload.notes, counts=counts,
        )
    except service.LaundryError as exc:
        raise _refused(exc) from None
    out = await _out(db, batch)
    await record_idempotent_response(db, idempotency_key, endpoint, 200, out.model_dump(mode="json"), current_db_user.id)
    return out


@router.get("/batches/{batch_id}/history", response_model=list[BatchEventOut])
async def batch_history(
    batch_id: uuid.UUID, current_db_user: CurrentDbUser, db: AsyncSession = Depends(get_db),
) -> list[BatchEventOut]:
    try:
        await service.get_scoped(db, batch_id, current_db_user.facility_id)
    except service.LaundryError as exc:
        raise _refused(exc) from None
    rows = (
        await db.execute(
            select(LinenBatchEvent, User.full_name)
            .join(User, User.id == LinenBatchEvent.changed_by)
            .where(LinenBatchEvent.batch_id == batch_id)
            .order_by(LinenBatchEvent.changed_at)
        )
    ).all()
    return [
        BatchEventOut(from_status=e.from_status, to_status=e.to_status, notes=e.notes, changed_by=name, changed_at=e.changed_at)
        for e, name in rows
    ]

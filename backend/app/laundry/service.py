"""Laundry batch rules: linen is counted out, moves forward one step at a
time, and is counted back. What does not come back is reported, not hidden."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import Bed, Ward
from app.laundry.models import LINEN_NEXT_STATUS, LinenBatch, LinenBatchEvent, LinenBatchItem


class LaundryError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


async def _scoped_ward(db: AsyncSession, ward_id: uuid.UUID, facility_id: uuid.UUID) -> Ward:
    ward = await db.get(Ward, ward_id)
    if ward is None or ward.facility_id != facility_id:
        raise LaundryError("ward_not_found", "Ward not found", 404)
    return ward


async def collect(
    db: AsyncSession, *, facility_id: uuid.UUID, user_id: uuid.UUID, items: list[tuple[str, int]],
    ward_id: uuid.UUID | None = None, bed_id: uuid.UUID | None = None, source: str | None = None,
    is_infected: bool = False, notes: str | None = None,
) -> LinenBatch:
    source = (source or "").strip() or None
    if ward_id is None and source is None:
        raise LaundryError("source_required", "Say where the linen came from: a ward, or a place such as OT 2", 422)
    if ward_id is not None:
        await _scoped_ward(db, ward_id, facility_id)
    if bed_id is not None:
        bed = await db.get(Bed, bed_id)
        if bed is None or bed.ward_id != ward_id:
            raise LaundryError("bed_not_found", "Bed not found in that ward", 404)
    merged: dict[str, int] = {}
    for item_type, quantity in items:
        merged[item_type] = merged.get(item_type, 0) + quantity
    if not merged or any(q <= 0 for q in merged.values()):
        raise LaundryError("items_required", "Count at least one item", 422)
    now = datetime.now(UTC)
    batch = LinenBatch(
        id=uuid.uuid4(), facility_id=facility_id, ward_id=ward_id, bed_id=bed_id, source=source,
        is_infected=is_infected, status="collected", notes=(notes or "").strip() or None,
        collected_by=user_id, collected_at=now,
    )
    db.add(batch)
    for item_type, quantity in merged.items():
        db.add(LinenBatchItem(
            id=uuid.uuid4(), batch_id=batch.id, facility_id=facility_id, item_type=item_type, quantity=quantity,
            condemned_quantity=0,
        ))
    db.add(LinenBatchEvent(
        id=uuid.uuid4(), batch_id=batch.id, facility_id=facility_id, from_status=None, to_status="collected",
        notes="infected linen" if is_infected else None, changed_by=user_id, changed_at=now,
    ))
    await db.flush()
    return batch


async def get_scoped(db: AsyncSession, batch_id: uuid.UUID, facility_id: uuid.UUID, *, lock: bool = False) -> LinenBatch:
    stmt = select(LinenBatch).where(LinenBatch.id == batch_id, LinenBatch.facility_id == facility_id)
    if lock:
        stmt = stmt.with_for_update()
    batch = (await db.execute(stmt)).scalar_one_or_none()
    if batch is None:
        raise LaundryError("batch_not_found", "Laundry batch not found", 404)
    return batch


async def items_of(db: AsyncSession, batch_id: uuid.UUID) -> list[LinenBatchItem]:
    return list(
        (await db.execute(select(LinenBatchItem).where(LinenBatchItem.batch_id == batch_id).order_by(LinenBatchItem.item_type)))
        .scalars()
    )


async def advance(
    db: AsyncSession, batch: LinenBatch, *, to_status: str, user_id: uuid.UUID, notes: str | None = None,
    counts: dict[str, tuple[int, int]] | None = None,
) -> LinenBatch:
    """Move one step forward. Returning needs every line counted back as
    (returned, condemned); the rest of a line is missing."""
    expected = LINEN_NEXT_STATUS.get(batch.status)
    if expected is None:
        raise LaundryError("batch_returned", "This batch has already been returned")
    if to_status != expected:
        raise LaundryError("wrong_step", f"A {batch.status} batch goes to {expected} next, not {to_status}")
    now = datetime.now(UTC)
    if to_status == "returned":
        lines = await items_of(db, batch.id)
        counts = counts or {}
        if set(counts) != {line.item_type for line in lines}:
            raise LaundryError("count_every_item", "Count back every item type in the batch", 422)
        for line in lines:
            returned, condemned = counts[line.item_type]
            if returned < 0 or condemned < 0 or returned + condemned > line.quantity:
                raise LaundryError(
                    "count_exceeds_sent",
                    f"{line.item_type}: {returned} returned and {condemned} condemned is more than the {line.quantity} sent",
                    422,
                )
            line.returned_quantity, line.condemned_quantity = returned, condemned
        batch.returned_at = now
    notes = (notes or "").strip() or None
    db.add(LinenBatchEvent(
        id=uuid.uuid4(), batch_id=batch.id, facility_id=batch.facility_id, from_status=batch.status,
        to_status=to_status, notes=notes, changed_by=user_id, changed_at=now,
    ))
    batch.status = to_status
    await db.flush()
    return batch

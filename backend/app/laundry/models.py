"""Laundry: linen leaves a ward in a batch and is counted back (migration 0104).

A batch is one collection: so many bed sheets, pillow covers and blankets from
a ward (or from one bed after a discharge clean). It moves collected ->
washing -> ready -> returned, and every move is an event with who and when.
On return each item line is counted back: returned, condemned (torn, stained
beyond use) and the shortfall, which is what a linen audit asks about.

Infected linen (isolation rooms, blood or body fluid) is flagged at collection
so the laundry washes it apart; the flag cannot be removed afterwards.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk

LINEN_ITEM_TYPES = (
    "bed_sheet", "draw_sheet", "pillow_cover", "blanket", "patient_gown", "towel", "curtain", "ot_linen", "other",
)
LINEN_BATCH_STATUSES = ("collected", "washing", "ready", "returned")
#: The only forward path. A batch never goes back a step: a mistake is a note, not an undo.
LINEN_NEXT_STATUS = {"collected": "washing", "washing": "ready", "ready": "returned"}


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class LinenBatch(Base, UUIDPk, Timestamps):
    __tablename__ = "linen_batches"
    __audit_resource_type__ = "linen_batches"
    __audit_facility_id_field__ = "facility_id"
    __table_args__ = (
        CheckConstraint(f"status IN ({_in(LINEN_BATCH_STATUSES)})", name="ck_linen_batches_status"),
        Index("ix_linen_batches_facility_status", "facility_id", "status"),
        Index("ix_linen_batches_ward_id", "ward_id"),
        Index("ix_linen_batches_bed_id", "bed_id"),
        Index("ix_linen_batches_collected_by", "collected_by"),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    #: Where it came from and goes back to. NULL for OT or a central store.
    ward_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("wards.id", ondelete="RESTRICT"))
    bed_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("beds.id", ondelete="RESTRICT"))
    #: Free text for a source that is not a ward: "OT 2", "Labour room".
    source: Mapped[str | None] = mapped_column(String(120))
    is_infected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="collected", server_default="collected")
    notes: Mapped[str | None] = mapped_column(Text)
    collected_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LinenBatchItem(Base, UUIDPk):
    __tablename__ = "linen_batch_items"
    __audit_resource_type__ = "linen_batch_items"
    __audit_facility_id_field__ = "facility_id"
    __table_args__ = (
        CheckConstraint(f"item_type IN ({_in(LINEN_ITEM_TYPES)})", name="ck_linen_batch_items_item_type"),
        CheckConstraint("quantity > 0 AND quantity <= 1000", name="ck_linen_batch_items_quantity"),
        CheckConstraint(
            "returned_quantity IS NULL OR (returned_quantity >= 0 AND condemned_quantity >= 0 "
            "AND returned_quantity + condemned_quantity <= quantity)",
            name="ck_linen_batch_items_counted_back",
        ),
        Index("uq_linen_batch_items_batch_type", "batch_id", "item_type", unique=True),
        Index("ix_linen_batch_items_facility_id", "facility_id"),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("linen_batches.id", ondelete="RESTRICT"), nullable=False
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Counted back on return; NULL until then. quantity - returned - condemned is missing.
    returned_quantity: Mapped[int | None] = mapped_column(Integer)
    condemned_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class LinenBatchEvent(Base, UUIDPk):
    """Append-only: one row per status change, including collection."""

    __tablename__ = "linen_batch_events"
    __audit_resource_type__ = "linen_batch_events"
    __audit_facility_id_field__ = "facility_id"
    __table_args__ = (
        CheckConstraint(f"to_status IN ({_in(LINEN_BATCH_STATUSES)})", name="ck_linen_batch_events_to"),
        Index("ix_linen_batch_events_batch", "batch_id", "changed_at"),
        Index("ix_linen_batch_events_facility_id", "facility_id"),
        Index("ix_linen_batch_events_changed_by", "changed_by"),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("linen_batches.id", ondelete="RESTRICT"), nullable=False
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(50))
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

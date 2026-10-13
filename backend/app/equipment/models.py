"""Equipment register and its status history (migration 0100).

A machine is working, down, in maintenance or retired. Every change is an
event with who, when and why, so "down since" is a fact the control room can
show rather than a guess. Audited per facility like every clinical module.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk

EQUIPMENT_STATUSES = ("working", "down", "maintenance", "retired")
EQUIPMENT_CATEGORIES = (
    "imaging", "laboratory", "life_support", "monitoring", "surgical", "sterilisation", "power", "cold_chain", "other",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Equipment(Base, UUIDPk, Timestamps):
    __tablename__ = "equipment"
    __audit_resource_type__ = "equipment"
    __audit_facility_id_field__ = "facility_id"
    __table_args__ = (
        CheckConstraint(f"status IN ({_in(EQUIPMENT_STATUSES)})", name="ck_equipment_status"),
        CheckConstraint(f"category IN ({_in(EQUIPMENT_CATEGORIES)})", name="ck_equipment_category"),
        CheckConstraint("trim(name) <> ''", name="ck_equipment_name"),
        UniqueConstraint("facility_id", "asset_tag", name="uq_equipment_facility_asset_tag"),
        Index("ix_equipment_facility_status", "facility_id", "status"),
        Index("ix_equipment_created_by", "created_by"),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    #: Where it stands: "ICU", "X-ray room 2". Free text: wards are not the only places machines live.
    location: Mapped[str | None] = mapped_column(String(120))
    asset_tag: Mapped[str | None] = mapped_column(String(60))
    #: A critical machine down turns the facility red, not amber (ventilator, oxygen plant, generator).
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="working", server_default="working")
    status_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class EquipmentStatusEvent(Base, UUIDPk):
    """Append-only: one row per status change."""

    __tablename__ = "equipment_status_events"
    __audit_resource_type__ = "equipment_status_events"
    __audit_facility_id_field__ = "facility_id"
    __table_args__ = (
        CheckConstraint(f"to_status IN ({_in(EQUIPMENT_STATUSES)})", name="ck_equipment_status_events_to"),
        Index("ix_equipment_status_events_equipment", "equipment_id", "changed_at"),
        Index("ix_equipment_status_events_facility_id", "facility_id"),
        Index("ix_equipment_status_events_changed_by", "changed_by"),
    )

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=False
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(50))
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk


class Supplier(Base, UUIDPk, Timestamps):
    __tablename__ = "suppliers"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    contact_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_suppliers_facility_id", "facility_id"),
    )


class InventoryItem(Base, UUIDPk, Timestamps):
    __tablename__ = "inventory_items"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    generic_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    strength: Mapped[str | None] = mapped_column(String(50), nullable=True)
    form: Mapped[str | None] = mapped_column(String(50), nullable=True)
    item_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_controlled_drug: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manufacturer: Mapped[str | None] = mapped_column(Text, nullable=True)
    owning_department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint(
            "form IN ('tablet','capsule','injection','syrup','ointment','fluid',"
            "'reagent','consumable','film','implant','blood_component')",
            name="form",
        ),
        CheckConstraint(
            "item_type IN ('medicine','reagent','consumable','film','implant',"
            "'blood_component')",
            name="item_type",
        ),
        Index("ix_inventory_items_owning_department_id", "owning_department_id"),
    )


class StockLocation(Base, UUIDPk, Timestamps):
    __tablename__ = "stock_locations"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    location_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "location_type IN ('central','pharmacy','lab','radiology','ward',"
            "'emergency','ot')",
            name="location_type",
        ),
        Index("ix_stock_locations_department_id", "department_id"),
        Index("ix_stock_locations_facility_id", "facility_id"),
    )


class InventoryBatch(Base, UUIDPk, Timestamps):
    __tablename__ = "inventory_batches"

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False
    )
    batch_number: Mapped[str] = mapped_column(String(50), nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    purchase_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    issue_rate_mrp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    stock_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_locations.id"), nullable=False
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        CheckConstraint("quantity >= 0", name="quantity"),
        UniqueConstraint(
            "item_id", "batch_number", "stock_location_id",
        ),
        Index("ix_inventory_batches_stock_location_id", "stock_location_id"),
    )


class StockLedger(Base, UUIDPk):
    __tablename__ = "stock_ledger"

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_batches.id"), nullable=True
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    performed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('purchase','issue','return','transfer',"
            "'consumption','adjustment','write_off')",
            name="transaction_type",
        ),
        CheckConstraint("quantity <> 0", name="quantity_nonzero"),
        CheckConstraint(
            "(transaction_type IN ('purchase','return') AND quantity > 0) OR "
            "(transaction_type IN ('issue','consumption','write_off') AND quantity < 0) OR "
            "(transaction_type IN ('adjustment','transfer'))",
            name="quantity_sign_matches_type",
        ),
        Index("ix_stock_ledger_item_id", "item_id"),
        Index("ix_stock_ledger_batch_id", "batch_id"),
        Index("ix_stock_ledger_performed_by", "performed_by"),
    )

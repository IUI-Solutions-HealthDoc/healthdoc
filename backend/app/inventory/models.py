import uuid
from sqlalchemy import (
    Column, String, Text, Boolean, Numeric, ForeignKey, DateTime, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.common.db import Base  # adjust to actual import path


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    name = Column(Text, nullable=False)
    contact_info = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        CheckConstraint(
            "form IN ('tablet','capsule','injection','syrup','ointment','fluid','reagent','consumable','film','implant','blood_component')",
            name="ck_inventory_items_form",
        ),
        CheckConstraint(
            "item_type IN ('medicine','reagent','consumable','film','implant','blood_component')",
            name="ck_inventory_items_item_type",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    name = Column(Text, nullable=False)
    generic_name = Column(Text)
    strength = Column(String(50))
    form = Column(String(50))
    item_type = Column(String(50))
    is_controlled_drug = Column(Boolean, nullable=False, default=False)
    manufacturer = Column(Text)
    owning_department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True)
    reorder_level = Column(Numeric(12, 2), nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StockLocation(Base):
    __tablename__ = "stock_locations"
    __table_args__ = (
        CheckConstraint(
            "location_type IN ('central','pharmacy','lab','radiology','ward','emergency','ot')",
            name="ck_stock_locations_location_type",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    name = Column(Text, nullable=False)
    location_type = Column(String(50))
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True)
    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InventoryBatch(Base):
    __tablename__ = "inventory_batches"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    item_id = Column(UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False)
    batch_number = Column(String(50), nullable=False)
    expiry_date = Column(DateTime(timezone=False), nullable=False)  # DATE in DB
    quantity = Column(Numeric(12, 2), nullable=False)
    purchase_rate = Column(Numeric(12, 2))
    issue_rate_mrp = Column(Numeric(12, 2))
    stock_location_id = Column(UUID(as_uuid=True), ForeignKey("stock_locations.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StockLedger(Base):
    """Append-only. No update/delete methods should ever be called on this
    model - the DB trigger trg_stock_ledger_block_update will reject it
    anyway, but don't rely on the trigger as your only guard; the service
    layer should never construct an UPDATE/DELETE against this table."""
    __tablename__ = "stock_ledger"
    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('purchase','issue','return','transfer','consumption','adjustment','write_off')",
            name="ck_stock_ledger_transaction_type",
        ),
        CheckConstraint("quantity <> 0", name="ck_stock_ledger_quantity_nonzero"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    item_id = Column(UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("inventory_batches.id"), nullable=True)
    transaction_type = Column(String(50), nullable=False)
    quantity = Column(Numeric(12, 2), nullable=False)
    reference_type = Column(String(30))
    reference_id = Column(UUID(as_uuid=True))
    performed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())



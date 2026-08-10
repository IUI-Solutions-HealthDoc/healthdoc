import uuid
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base
from app.common.enums import DispenseStatus
from app.common.models import Blame, Timestamps, UUIDPk


class PharmacyDispense(Base, UUIDPk, Timestamps):
    __tablename__ = "pharmacy_dispenses"

    prescription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prescriptions.id", ondelete="RESTRICT"), nullable=False
    )
    visit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("visits.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=DispenseStatus.RECEIVED.value
    )
    dispensed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.true())

    items: Mapped[list["PharmacyDispenseItem"]] = relationship(
        back_populates="dispense", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            DispenseStatus.sql_check("status"),
            name="status",
        ),
        UniqueConstraint(
            "prescription_id", "version",
        ),
        Index(
            "uq_pharmacy_dispenses_current",
            "prescription_id",
            unique=True,
            postgresql_where=sa.text("is_current"),
        ),
        Index("ix_pharmacy_dispenses_visit_id", "visit_id"),
        Index("ix_pharmacy_dispenses_dispensed_by", "dispensed_by"),
    )


class PharmacyDispenseItem(Base, UUIDPk, Timestamps):
    __tablename__ = "pharmacy_dispense_items"

    dispense_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pharmacy_dispenses.id", ondelete="CASCADE"), nullable=False
    )
    prescription_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prescription_items.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_batches.id", ondelete="RESTRICT"), nullable=True
    )
    quantity_prescribed: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    quantity_dispensed: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    is_substitute: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
    substitute_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="not_required"
    )
    substitute_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expiry_override_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    expiry_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    dispense: Mapped["PharmacyDispense"] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint(
            "approval_status IN ('not_required', 'pending', 'approved', 'rejected')",
            name="approval_status",
        ),
        CheckConstraint(
            "quantity_dispensed IS NULL OR quantity_dispensed >= 0",
            name="quantity_dispensed_nonneg",
        ),
        CheckConstraint(
            "quantity_dispensed IS NULL OR quantity_prescribed IS NULL "
            "OR quantity_dispensed <= quantity_prescribed",
            name="dispensed_not_over_prescribed",
        ),
        CheckConstraint(
            "NOT is_substitute OR substitute_reason IS NOT NULL",
            name="substitute_reason_required",
        ),
        Index("ix_pharmacy_dispense_items_dispense_id", "dispense_id"),
        Index("ix_pharmacy_dispense_items_prescription_item_id", "prescription_item_id"),
        Index("ix_pharmacy_dispense_items_batch_id", "batch_id"),
        Index("ix_pharmacy_dispense_items_substitute_item_id", "substitute_item_id"),
    )


class Grn(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "grn"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    invoice_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    received_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','received','verified','cancelled')",
            name="status",
        ),
        Index("ix_grn_facility_id", "facility_id"),
        Index("ix_grn_supplier_id", "supplier_id"),
        Index("ix_grn_created_by", "created_by"),
        Index("ix_grn_updated_by", "updated_by"),
    )


class GrnItem(Base, UUIDPk, Timestamps):
    __tablename__ = "grn_items"

    grn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grn.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False
    )
    batch_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("ix_grn_items_grn_id", "grn_id"),
        Index("ix_grn_items_item_id", "item_id"),
    )


class Indent(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "indents"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('requested','approved','rejected','issued')",
            name="status",
        ),
        Index("ix_indents_facility_id", "facility_id"),
        Index("ix_indents_department_id", "department_id"),
        Index("ix_indents_approved_by", "approved_by"),
        Index("ix_indents_created_by", "created_by"),
        Index("ix_indents_updated_by", "updated_by"),
    )


class IndentItem(Base, UUIDPk, Timestamps):
    __tablename__ = "indent_items"

    indent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("indents.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False
    )
    quantity_requested: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "quantity_requested > 0",
            name="quantity_requested_positive",
        ),
        Index("ix_indent_items_indent_id", "indent_id"),
        Index("ix_indent_items_item_id", "item_id"),
    )


class Adjustment(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "adjustments"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_batches.id"), nullable=False
    )
    quantity_change: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    first_approver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    second_approver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "quantity_change <> 0",
            name="quantity_change_nonzero",
        ),
        CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="status",
        ),
        CheckConstraint(
            "first_approver_id <> second_approver_id",
            name="distinct_approvers",
        ),
        CheckConstraint(
            "status <> 'approved' OR second_approver_id IS NOT NULL",
            name="second_approver_required_when_approved",
        ),
        CheckConstraint(
            "created_by <> first_approver_id",
            name="creator_not_first_approver",
        ),
        CheckConstraint(
            "second_approver_id IS NULL OR created_by <> second_approver_id",
            name="creator_not_second_approver",
        ),
        Index("ix_adjustments_facility_id", "facility_id"),
        Index("ix_adjustments_item_id", "item_id"),
        Index("ix_adjustments_batch_id", "batch_id"),
        Index("ix_adjustments_first_approver_id", "first_approver_id"),
        Index("ix_adjustments_second_approver_id", "second_approver_id"),
        Index("ix_adjustments_created_by", "created_by"),
        Index("ix_adjustments_updated_by", "updated_by"),
    )


class FacilitySettings(Base, Timestamps):
    __tablename__ = "facility_settings"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id"), primary_key=True
    )
    stock_deduction_policy: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "stock_deduction_policy IN ('on_acceptance','on_dispense')",
            name="stock_deduction_policy",
        ),
    )

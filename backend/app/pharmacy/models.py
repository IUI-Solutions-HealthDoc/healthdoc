from sqlalchemy import (
    Column, String, Text, Boolean, Numeric, Integer, ForeignKey, DateTime, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.common.db import Base  # adjust to actual import path


class PharmacyDispense(Base):
    __tablename__ = "pharmacy_dispenses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('received','in_progress','partially_dispensed','dispensed',"
            "'out_of_stock','substitute_suggested','doctor_approval_required','returned','cancelled')",
            name="ck_pharmacy_dispenses_status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    prescription_id = Column(UUID(as_uuid=True), ForeignKey("prescriptions.id"), nullable=False)
    visit_id = Column(UUID(as_uuid=True), ForeignKey("visits.id"), nullable=True)
    status = Column(String(50), nullable=False)
    dispensed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    version = Column(Integer, nullable=False)
    is_current = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PharmacyDispenseItem(Base):
    __tablename__ = "pharmacy_dispense_items"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    dispense_id = Column(UUID(as_uuid=True), ForeignKey("pharmacy_dispenses.id", ondelete="CASCADE"), nullable=False)
    prescription_item_id = Column(UUID(as_uuid=True), ForeignKey("prescription_items.id"), nullable=False)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("inventory_batches.id"), nullable=False)
    quantity_prescribed = Column(Numeric(12, 2))
    quantity_dispensed = Column(Numeric(12, 2))
    is_substitute = Column(Boolean, nullable=False, default=False)
    substitute_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Grn(Base):
    __tablename__ = "grn"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','received','verified','cancelled')",
            name="ck_grn_status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    invoice_number = Column(String(50))
    received_date = Column(DateTime(timezone=False), nullable=False)  # DATE in DB
    status = Column(String(50), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GrnItem(Base):
    __tablename__ = "grn_items"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    grn_id = Column(UUID(as_uuid=True), ForeignKey("grn.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False)
    batch_number = Column(String(50))
    expiry_date = Column(DateTime(timezone=False))  # DATE in DB
    quantity = Column(Numeric(12, 2), nullable=False)
    unit_price = Column(Numeric(12, 2))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Indent(Base):
    __tablename__ = "indents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested','approved','rejected','issued')",
            name="ck_indents_status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    status = Column(String(50), nullable=False)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IndentItem(Base):
    __tablename__ = "indent_items"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    indent_id = Column(UUID(as_uuid=True), ForeignKey("indents.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False)
    quantity_requested = Column(Numeric(12, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Adjustment(Base):
    __tablename__ = "adjustments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_adjustments_status",
        ),
        CheckConstraint(
            "first_approver_id <> second_approver_id",
            name="ck_adjustments_distinct_approvers",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    item_id = Column(UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("inventory_batches.id"), nullable=False)
    quantity_change = Column(Numeric(12, 2), nullable=False)
    reason = Column(Text, nullable=False)
    first_approver_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    second_approver_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(String(50), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FacilitySettings(Base):
    __tablename__ = "facility_settings"
    __table_args__ = (
        CheckConstraint(
            "stock_deduction_policy IN ('on_acceptance','on_dispense')",
            name="ck_facility_settings_stock_deduction_policy",
        ),
    )

    # deliberate exception to the generic `id` PK rule - one config row
    # per facility, not an entity list
    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id"), primary_key=True)
    stock_deduction_policy = Column(String(50))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

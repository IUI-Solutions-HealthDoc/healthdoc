from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB

from sqlalchemy.orm import relationship
from app.common.db import Base
from app.common.enums import OrderPriority, OrderStatus, OrderType, ResultStatus
from app.common.models import Blame, Timestamps, UUIDPk


class Order(Base, UUIDPk, Timestamps, Blame):
    """schema.md §3, 0008 — the single order header for every department.
    Lab/radiology add their OWN detail rows later (migrations 0010/0011)
    that point back at this table via order_id. Don't put lab-specific
    or radiology-specific columns here.
    """
    __tablename__ = "orders"

    order_number = Column(String(30), unique=True, nullable=False)
    encounter_id = Column(
        UUID(as_uuid=True), ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    order_type = Column(String(50), nullable=False)
    priority = Column(String(50), nullable=False, server_default=OrderPriority.ROUTINE.value)
    status = Column(String(50), nullable=False, server_default=OrderStatus.PLACED.value)
    ordered_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(OrderType.sql_check("order_type"), name="ck_orders_order_type"),
        CheckConstraint(OrderPriority.sql_check("priority"), name="ck_orders_priority"),
        CheckConstraint(OrderStatus.sql_check("status"), name="ck_orders_status"),
        Index("ix_orders_order_type_status", "order_type", "status"),
        Index("ix_orders_patient_id", "patient_id"),
        Index("ix_orders_encounter_id", "encounter_id"),
    )


class Prescription(Base, UUIDPk, Timestamps, Blame):
    """schema.md §3, 0008 — header only. Drugs live in PrescriptionItem
    below (one row per drug), never as one big text blob here."""
    __tablename__ = "prescriptions"

    encounter_id = Column(
        UUID(as_uuid=True), ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    notes = Column(Text, nullable=True)

    items = relationship(
        "PrescriptionItem", back_populates="prescription", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_prescriptions_encounter_id", "encounter_id"),
        Index("ix_prescriptions_patient_id", "patient_id"),
    )


class PrescriptionItem(Base, UUIDPk, Timestamps):
    """One row per drug on a prescription.
    medicine_item_id has no FK constraint yet — inventory_items doesn't
    exist until migration 0012. The FK gets added later in that
    migration with op.create_foreign_key(), same pattern as
    patients.photo_file_id waiting on migration 0019.
    """
    __tablename__ = "prescription_items"

    prescription_id = Column(
        UUID(as_uuid=True), ForeignKey("prescriptions.id", ondelete="CASCADE"), nullable=False
    )
    prescription = relationship("Prescription", back_populates="items")
    medicine_item_id = Column(UUID(as_uuid=True), nullable=True)  # FK added in migration 0012
    medicine_name = Column(Text, nullable=False)
    dosage = Column(String(50), nullable=True)
    frequency = Column(String(50), nullable=True)
    duration_days = Column(Integer, nullable=True)
    route = Column(String(30), nullable=True)
    instructions = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, server_default="prescribed")

    __table_args__ = (
        Index("ix_prescription_items_prescription_id", "prescription_id"),
    )

class Result(Base, UUIDPk, Timestamps, Blame):
    """schema.md — B3-W4-01. One row per order's result. Tracks the raw
    result separately from the doctor's review/sign-off, since those
    happen at different times by different people."""
    __tablename__ = "results"

    order_id = Column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    result_status = Column(String(50), nullable=False, server_default="pending")
    result_text = Column(Text, nullable=True)
    result_data = Column(JSONB, nullable=True)
    performed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    performed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_notes = Column(Text, nullable=True)
    is_signed_off = Column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        CheckConstraint(ResultStatus.sql_check("result_status"), name="ck_results_result_status"),
        Index("ix_results_order_id", "order_id"),
    )

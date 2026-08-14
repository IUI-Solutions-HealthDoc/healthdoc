from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.common.db import Base
from app.common.enums import OrderPriority, OrderStatus, OrderType
from app.common.models import Blame, Timestamps, UUIDPk


class OrderNumberCounter(Base, UUIDPk, Timestamps):
    """Gapless per-facility-per-business-day allocator for order_number, same pattern as visit_number_counters."""
    __tablename__ = "order_number_counters"
    __table_args__ = (
        UniqueConstraint("facility_id", "counter_date", name="uq_order_number_counters_facility_id_counter_date"),
    )

    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    counter_date = Column(Date, nullable=False)
    seq = Column(Integer, nullable=False, server_default="0")


class Order(Base, UUIDPk, Timestamps, Blame):
    """schema.md §3, 0008 — the single order header for every department.

    Lab/radiology add their OWN detail rows later (migrations 0010/0011)
    that point back at this table via order_id. Don't put lab-specific
    or radiology-specific columns here.
    """

    __tablename__ = "orders"

    order_number = Column(String(30), unique=True, nullable=False)
    __audit_resource_type__ = "orders"
    __audit_facility_id_field__ = "facility_id"
    __audit_encounter_id_field__ = "encounter_id"

    encounter_id = Column(
        UUID(as_uuid=True), ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=False
    )
    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    order_type = Column(String(50), nullable=False)
    priority = Column(String(50), nullable=False, server_default=OrderPriority.ROUTINE.value)
    status = Column(String(50), nullable=False, server_default=OrderStatus.PLACED.value)
    ordered_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(OrderType.sql_check("order_type"), name="order_type"),
        CheckConstraint(OrderPriority.sql_check("priority"), name="priority"),
        CheckConstraint(OrderStatus.sql_check("status"), name="status"),
        Index("ix_orders_order_type_status", "order_type", "status"),
        Index("ix_orders_patient_id", "patient_id"),
        Index("ix_orders_encounter_id", "encounter_id"),
    )


class Prescription(Base, UUIDPk, Timestamps, Blame):
    """schema.md §3, 0008 — header only. Drugs live in PrescriptionItem
    below (one row per drug), never as one big text blob here."""

    __tablename__ = "prescriptions"

    __audit_resource_type__ = "prescriptions"
    __audit_facility_id_field__ = "facility_id"
    __audit_encounter_id_field__ = "encounter_id"

    encounter_id = Column(
        UUID(as_uuid=True), ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=False
    )
    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    notes = Column(Text, nullable=True)

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
    medicine_item_id = Column(UUID(as_uuid=True), nullable=True)  # FK added in migration 0012
    medicine_name = Column(Text, nullable=False)
    dosage = Column(String(50), nullable=True)
    frequency = Column(String(50), nullable=True)
    duration_days = Column(Integer, nullable=True)
    route = Column(String(30), nullable=True)
    instructions = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, server_default="prescribed")

    # Allergy override trail (migration 0032). Both NULL = no conflict was
    # ever raised for this item. Both set = a conflict was raised and a
    # clinician overrode it -- the CHECK below enforces "all or nothing"
    # and the 20-char floor, mirroring the DB constraint exactly so an ORM
    # write can never produce a half-recorded override.
    allergy_override_reason = Column(Text, nullable=True)
    allergy_override_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        Index("ix_prescription_items_prescription_id", "prescription_id"),
        CheckConstraint(
            "(allergy_override_reason IS NULL AND allergy_override_by IS NULL) "
            "OR (char_length(allergy_override_reason) >= 20 AND allergy_override_by IS NOT NULL)",
            name="allergy_override",
        ),
    )
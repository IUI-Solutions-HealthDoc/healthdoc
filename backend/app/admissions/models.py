from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.common.db import Base
from app.common.enums import AdmissionStatus, BedStatus, DischargeType
from app.common.models import Blame, Timestamps, UUIDPk


class Ward(Base, UUIDPk, Timestamps):
    __tablename__ = "wards"

    name = Column(Text, nullable=False)
    department_id = Column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=True
    )
    facility_id = Column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    is_active = Column(Boolean, nullable=False, server_default="true")

    __table_args__ = (
        Index("ix_wards_department_id", "department_id"),
        Index("ix_wards_facility_id", "facility_id"),
    )


class Bed(Base, UUIDPk, Timestamps):
    __tablename__ = "beds"

    ward_id = Column(UUID(as_uuid=True), ForeignKey("wards.id", ondelete="RESTRICT"), nullable=False)
    bed_number = Column(String(20), nullable=False)
    status = Column(String(50), nullable=False, server_default=BedStatus.VACANT.value)

    __table_args__ = (
        UniqueConstraint("ward_id", "bed_number", name="uq_beds_ward_id_bed_number"),
        CheckConstraint(BedStatus.sql_check("status"), name="status"),
    )


class Admission(Base, UUIDPk, Timestamps, Blame):
    """schema.md §3, 0015 — real FKs to ward/bed, never varchar names.

    uq_admissions_active_bed (0034): partial unique on bed_id WHERE
    status='admitted' -- one active admission per bed. Mirrored here from
    the migration (it existed in the DB but not the ORM, so SQLite tests
    couldn't catch a double-booking bug the same way Postgres would)."""

    __tablename__ = "admissions"

    visit_id = Column(UUID(as_uuid=True), ForeignKey("visits.id", ondelete="RESTRICT"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    ward_id = Column(UUID(as_uuid=True), ForeignKey("wards.id", ondelete="RESTRICT"), nullable=False)
    bed_id = Column(UUID(as_uuid=True), ForeignKey("beds.id", ondelete="RESTRICT"), nullable=False)
    admitted_at = Column(DateTime(timezone=True), nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, server_default=AdmissionStatus.ADMITTED.value)

    __table_args__ = (
        CheckConstraint(AdmissionStatus.sql_check("status"), name="status"),
        Index("ix_admissions_visit_id", "visit_id"),
        Index("ix_admissions_patient_id", "patient_id"),
        Index("ix_admissions_ward_id", "ward_id"),
        Index("ix_admissions_bed_id", "bed_id"),
        Index("uq_admissions_active_bed", "bed_id", unique=True,
              sqlite_where=(status == "admitted"), postgresql_where=(status == "admitted")),
    )


class Discharge(Base, UUIDPk, Timestamps, Blame):
    """discharge is never hard-blocked by unpaid invoice for
    emergency/DAMA cases — architecture.md §20.2 / ADR 0002.
    Long-form discharge_summary text goes to Mongo clinical_notes
    eventually; kept as a plain text column here for MVP simplicity.

    destination_facility_id/name (0034): where a 'transferred' discharge
    sends the patient -- FK for another facility we run, free text for one
    we don't. Required (one of the two) when discharge_type='transferred',
    mirrored here from the migration's CHECK constraint."""

    __tablename__ = "discharges"

    admission_id = Column(
        UUID(as_uuid=True), ForeignKey("admissions.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    discharged_at = Column(DateTime(timezone=True), nullable=False)
    discharge_type = Column(String(50), nullable=False)
    discharge_summary = Column(Text, nullable=True)
    follow_up_date = Column(Date, nullable=True)
    destination_facility_id = Column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=True
    )
    destination_facility_name = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(DischargeType.sql_check("discharge_type"), name="discharge_type"),
        CheckConstraint(
            "discharge_type <> 'transferred' OR destination_facility_id IS NOT NULL "
            "OR destination_facility_name IS NOT NULL",
            name="ck_discharges_transfer_destination",
        ),
        Index("ix_discharges_destination_facility_id", "destination_facility_id"),
        # admission_id is already unique, so no separate index needed
        # per the §3 blanket FK-index rule.
    )


class PatientMovementLog(Base, UUIDPk, Timestamps):
    """schema.md §3, 0023 — append-only ward/bed transfer trail. No
    facility_id (transfers are scoped through admission_id -> visit ->
    facility, same as lab_order_items/radiology_order_items don't carry
    their own facility_id either)."""

    __tablename__ = "patient_movement_log"

    admission_id = Column(UUID(as_uuid=True), ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=False)
    from_ward_id = Column(UUID(as_uuid=True), ForeignKey("wards.id", ondelete="RESTRICT"), nullable=True)
    from_bed_id = Column(UUID(as_uuid=True), ForeignKey("beds.id", ondelete="RESTRICT"), nullable=True)
    to_ward_id = Column(UUID(as_uuid=True), ForeignKey("wards.id", ondelete="RESTRICT"), nullable=False)
    to_bed_id = Column(UUID(as_uuid=True), ForeignKey("beds.id", ondelete="RESTRICT"), nullable=False)
    moved_at = Column(DateTime(timezone=True), nullable=False)
    reason = Column(Text, nullable=True)
    moved_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    __table_args__ = (
        Index("ix_patient_movement_log_admission_id_moved_at", "admission_id", "moved_at"),
    )


class DischargeNotification(Base, UUIDPk, Timestamps):
    """schema.md §3, 0026 — durable, not fire-and-forget: UNIQUE
    (discharge_id, target_module) means a retry updates the existing row
    rather than queuing pharmacy a second reminder."""

    __tablename__ = "discharge_notifications"

    discharge_id = Column(UUID(as_uuid=True), ForeignKey("discharges.id", ondelete="RESTRICT"), nullable=False)
    target_module = Column(String(30), nullable=False)
    status = Column(String(50), nullable=False, server_default="queued")
    sent_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)

    __table_args__ = (
        UniqueConstraint("discharge_id", "target_module",
                          name="uq_discharge_notifications_discharge_id_target_module"),
        CheckConstraint(
            "target_module IN ('pharmacy','billing','nursing','lab','radiology','patient')",
            name="ck_discharge_notifications_target_module",
        ),
        Index("ix_discharge_notifications_discharge_id", "discharge_id"),
    )

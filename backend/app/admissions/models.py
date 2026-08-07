from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.common.database import Base
from app.common.enums import AdmissionStatus, BedStatus, DischargeType
from app.common.mixins import Blame, Timestamps, UUIDPk


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
        CheckConstraint(BedStatus.sql_check("status"), name="ck_beds_status"),
    )


class Admission(Base, UUIDPk, Timestamps, Blame):
    """schema.md §3, 0015 — real FKs to ward/bed, never varchar names."""

    __tablename__ = "admissions"

    visit_id = Column(UUID(as_uuid=True), ForeignKey("visits.id", ondelete="RESTRICT"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    ward_id = Column(UUID(as_uuid=True), ForeignKey("wards.id", ondelete="RESTRICT"), nullable=False)
    bed_id = Column(UUID(as_uuid=True), ForeignKey("beds.id", ondelete="RESTRICT"), nullable=False)
    admitted_at = Column(DateTime(timezone=True), nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, server_default=AdmissionStatus.ADMITTED.value)

    __table_args__ = (
        CheckConstraint(AdmissionStatus.sql_check("status"), name="ck_admissions_status"),
        Index("ix_admissions_visit_id", "visit_id"),
        Index("ix_admissions_patient_id", "patient_id"),
        Index("ix_admissions_ward_id", "ward_id"),
        Index("ix_admissions_bed_id", "bed_id"),
    )


class Discharge(Base, UUIDPk, Timestamps, Blame):
    """discharge is never hard-blocked by unpaid invoice for
    emergency/DAMA cases — architecture.md §20.2 / ADR 0002.
    Long-form discharge_summary text goes to Mongo clinical_notes
    eventually; kept as a plain text column here for MVP simplicity."""

    __tablename__ = "discharges"

    admission_id = Column(
        UUID(as_uuid=True), ForeignKey("admissions.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    discharged_at = Column(DateTime(timezone=True), nullable=False)
    discharge_type = Column(String(50), nullable=False)
    discharge_summary = Column(Text, nullable=True)
    follow_up_date = Column(Date, nullable=True)

    __table_args__ = (
        CheckConstraint(DischargeType.sql_check("discharge_type"), name="ck_discharges_discharge_type"),
        # admission_id is already unique, so no separate index needed
        # per the §3 blanket FK-index rule.
    )
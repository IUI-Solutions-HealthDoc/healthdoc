import uuid
from datetime import date, datetime
from sqlalchemy import ForeignKey, String, Text, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import UUIDPk, Timestamps, Blame
from app.common.enums import AdmissionStatus, DischargeType, BedStatus


class Ward(Base, UUIDPk, Timestamps):
    __tablename__ = "wards"
    name: Mapped[str] = mapped_column(Text, nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class Bed(Base, UUIDPk, Timestamps):
    __tablename__ = "beds"
    __table_args__ = (
        UniqueConstraint("ward_id", "bed_number", name="uq_beds_ward_id_bed_number"),
        CheckConstraint(BedStatus.sql_check("status"), name="ck_beds_status"),
    )
    ward_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wards.id"), nullable=False, index=True
    )
    bed_number: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="vacant", nullable=False)


class Admission(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "admissions"
    __table_args__ = (
        CheckConstraint(AdmissionStatus.sql_check("status"), name="ck_admissions_status"),
    )
    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("visits.id"), nullable=False, index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True
    )
    ward_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wards.id"), nullable=False, index=True
    )
    bed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("beds.id"), nullable=False, index=True
    )
    admitted_at: Mapped[datetime] = mapped_column(nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="admitted", nullable=False)


class Discharge(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "discharges"
    __table_args__ = (
        CheckConstraint(DischargeType.sql_check("discharge_type"), name="ck_discharges_type"),
    )
    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admissions.id"), unique=True, nullable=False
    )
    discharged_at: Mapped[datetime] = mapped_column(nullable=False)
    discharge_type: Mapped[str] = mapped_column(String(50), nullable=False)
    discharge_summary: Mapped[str | None] = mapped_column(Text)
    follow_up_date: Mapped[date | None] = mapped_column(nullable=True)


class PatientMovementLog(Base, UUIDPk, Timestamps):
    __tablename__ = "patient_movement_log"
    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admissions.id"), nullable=False, index=True
    )
    from_ward_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("wards.id"))
    from_bed_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("beds.id"))
    to_ward_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wards.id"), nullable=False
    )
    to_bed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("beds.id"), nullable=False
    )
    moved_at: Mapped[datetime] = mapped_column(nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    moved_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
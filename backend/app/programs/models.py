"""SQLAlchemy models for longitudinal care programs, enrolments, and tracking visits (HD-28)."""
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk
from app.patients.models import Patient  # noqa: F401
from app.users.models import Facility, User  # noqa: F401


class CareProgram(Base, UUIDPk, Timestamps):
    __tablename__ = "care_programs"

    program_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    program_name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="chronic")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ProgramEnrolment(Base, UUIDPk, Timestamps):
    __tablename__ = "program_enrolments"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    program_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    program_name: Mapped[str] = mapped_column(String(100), nullable=False)
    enrolment_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_outcomes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    enrolled_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        Index("uq_active_program_enrolment", "patient_id", "program_code"),
    )


class ProgramVisit(Base, UUIDPk, Timestamps):
    __tablename__ = "program_visits"

    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("program_enrolments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="scheduled")
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    clinical_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    conducted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

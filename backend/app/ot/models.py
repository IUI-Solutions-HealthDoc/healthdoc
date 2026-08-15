"""SQLAlchemy models for the OT module: ot_schedules, ot_records
(migration 0017). Schema doc Section 3 "0017 - OT stubs" (B3, schema only).
B3-W1-02 (#137).
"""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, CheckConstraint, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import UUIDPk, Timestamps, Blame
from app.common.enums import OtStatus


class OtSchedule(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "ot_schedules"
    __table_args__ = (
        CheckConstraint(OtStatus.sql_check("status"), name="status"),
        CheckConstraint(
            "scheduled_end > scheduled_start", name="time_order"
        ),
    )

    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("visits.id"), nullable=False, index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False, index=True
    )
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    procedure_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="scheduled", nullable=False)


class OtRecord(Base, UUIDPk, Timestamps):
    __tablename__ = "ot_records"
    __table_args__ = (
        CheckConstraint(
            "started_at IS NULL OR ended_at IS NULL OR ended_at > started_at",
            name="time_order",
        ),
    )

    ot_schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ot_schedules.id"), nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    surgeon_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    anesthetist_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

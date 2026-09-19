import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.admissions.models import Admission  # noqa: F401
from app.common.db import Base
from app.common.enums import OtStatus
from app.common.models import Blame, Timestamps, UUIDPk
from app.opd.models import Visit  # noqa: F401
from app.patients.models import Patient  # noqa: F401
from app.users.models import Facility, User  # noqa: F401


class OtSchedule(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "ot_schedules"
    __table_args__ = (
        CheckConstraint(OtStatus.sql_check("status"), name="status"),
        CheckConstraint("scheduled_end > scheduled_start", name="time_order"),
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
    theatre_number: Mapped[str] = mapped_column(String(50), default="OT-1", nullable=False)
    admission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admissions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    pre_op_checklist: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    surgical_safety_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


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
    pre_op_diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_op_diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    procedure_performed: Mapped[str | None] = mapped_column(Text, nullable=True)
    anesthesia_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scrub_nurse: Mapped[str | None] = mapped_column(Text, nullable=True)
    circulating_nurse: Mapped[str | None] = mapped_column(Text, nullable=True)
    implants_used: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    sponge_needle_count_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    specimens_sent: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    complications: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovery_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

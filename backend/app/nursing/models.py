import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, String, Text, Integer, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import UUIDPk, Timestamps
from app.common.enums import Shift, IntakeOutputType


class NursingHandoverNote(Base, UUIDPk, Timestamps):
    """Append-only SBAR shift handover. Schema doc §3-0023."""
    __tablename__ = "nursing_handover_notes"
    __table_args__ = (
        CheckConstraint(Shift.sql_check("shift"), name="ck_nursing_handover_notes_shift"),
    )

    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admissions.id"), nullable=False, index=True
    )
    shift: Mapped[str] = mapped_column(String(50), nullable=False)
    situation: Mapped[str | None] = mapped_column(Text)
    background: Mapped[str | None] = mapped_column(Text)
    assessment: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(Text)
    handed_over_to: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )


class IntakeOutputRecord(Base, UUIDPk, Timestamps):
    """IPD fluid balance. Schema doc §3-0023."""
    __tablename__ = "intake_output_records"
    __table_args__ = (
        CheckConstraint(
            IntakeOutputType.sql_check("entry_type"), name="ck_intake_output_records_entry_type"
        ),
        CheckConstraint("volume_ml > 0", name="ck_intake_output_records_volume_positive"),
    )

    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admissions.id"), nullable=False, index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(nullable=False)
    entry_type: Mapped[str] = mapped_column(String(50), nullable=False)
    volume_ml: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

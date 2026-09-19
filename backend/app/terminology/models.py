"""Specialty encounter models (migration 0080)."""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk


class SpecialtyEncounter(Base, UUIDPk, Timestamps):
    """Structured clinical specialty assessments (pediatric, cardiology, obstetrics) (0080)."""

    __tablename__ = "specialty_encounters"

    encounter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    specialty_type: Mapped[str] = mapped_column(String(50), nullable=False)
    clinical_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        Index("ix_specialty_encounters_encounter_id", "encounter_id"),
        Index("ix_specialty_encounters_patient_id", "patient_id"),
        Index("ix_specialty_encounters_created_by", "created_by"),
        Index("ix_specialty_encounters_specialty_type", "specialty_type"),
    )

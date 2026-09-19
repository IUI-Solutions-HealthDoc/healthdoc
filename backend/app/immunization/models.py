"""Immunization models (HD-29)."""
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk


class VaccineCatalogue(Base, UUIDPk, Timestamps):
    __tablename__ = "vaccine_catalogue"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    target_disease: Mapped[str] = mapped_column(String(200), nullable=False)
    standard_doses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    min_age_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    route: Mapped[str] = mapped_column(String(50), default="intramuscular", nullable=False)
    site: Mapped[str] = mapped_column(String(50), default="left_upper_arm", nullable=False)
    dose_quantity: Mapped[str] = mapped_column(String(50), default="0.5 ml", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ImmunizationRecord(Base, UUIDPk, Timestamps):
    __tablename__ = "immunization_records"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vaccine_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vaccine_catalogue.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vaccine_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    dose_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    administered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    batch_number: Mapped[str] = mapped_column(String(50), nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    site: Mapped[str | None] = mapped_column(String(50), nullable=True)
    route: Mapped[str | None] = mapped_column(String(50), nullable=True)
    administered_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    adverse_reaction: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

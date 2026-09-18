"""Appointments and service catalogue models."""

from __future__ import annotations

import uuid
from datetime import date
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base
from app.common.models import Blame, Timestamps, UUIDPk


class AppointmentService(Base, UUIDPk, Timestamps):
    __tablename__ = "appointment_services"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_appointment_services_facility_id", "facility_id"),
        Index("ix_appointment_services_department_id", "department_id"),
    )


class Appointment(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "appointments"
    __audit_resource_type__ = "appointments"
    __audit_facility_id_field__ = "facility_id"
    __audit_patient_id_field__ = "patient_id"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False
    )
    doctor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointment_services.id", ondelete="RESTRICT"), nullable=True
    )
    service_name: Mapped[str] = mapped_column(String(100), nullable=False, default="Consultation")
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    appointment_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[str] = mapped_column(String(10), nullable=False)
    end_time: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="booked")
    is_walk_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_teleconsult: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    teleconsult_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_from_visit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("visits.id", ondelete="RESTRICT"), nullable=True
    )
    visit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("visits.id", ondelete="RESTRICT"), nullable=True
    )
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("queue_tokens.id", ondelete="RESTRICT"), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('booked', 'confirmed', 'checked_in', 'completed', 'cancelled', 'no_show', 'rescheduled')",
            name="appointment_status",
        ),
        Index("ix_appointments_facility_date", "facility_id", "appointment_date"),
        Index("ix_appointments_doctor_date", "doctor_user_id", "appointment_date"),
        Index("ix_appointments_patient_id", "patient_id"),
        Index("ix_appointments_visit_id", "visit_id"),
    )

"""Pydantic schemas for appointments and service catalogue."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field


class AppointmentServiceCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    duration_minutes: int = Field(default=15, ge=5, le=240)
    department_id: uuid.UUID | None = None
    description: str | None = None


class AppointmentServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    facility_id: uuid.UUID
    department_id: uuid.UUID | None = None
    name: str
    duration_minutes: int
    is_active: bool
    description: str | None = None


class AppointmentCreate(BaseModel):
    patient_id: uuid.UUID
    department_id: uuid.UUID
    doctor_user_id: uuid.UUID | None = None
    service_id: uuid.UUID | None = None
    service_name: str = "Consultation"
    duration_minutes: int = Field(default=15, ge=5, le=240)
    appointment_date: date
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    is_walk_in: bool = False
    is_teleconsult: bool = False
    notes: str | None = None
    follow_up_from_visit_id: uuid.UUID | None = None


class AppointmentUpdate(BaseModel):
    appointment_date: date | None = None
    start_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    duration_minutes: int | None = Field(None, ge=5, le=240)
    doctor_user_id: uuid.UUID | None = None
    status: str | None = None
    cancellation_reason: str | None = None
    notes: str | None = None


class AppointmentCheckInRequest(BaseModel):
    queue_id: uuid.UUID | None = None
    priority: str = "normal"


class AppointmentCheckInResult(BaseModel):
    appointment_id: uuid.UUID
    status: str
    visit_id: uuid.UUID
    visit_number: str
    token_id: uuid.UUID | None = None
    token_display: str | None = None


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    facility_id: uuid.UUID
    patient_id: uuid.UUID
    department_id: uuid.UUID
    doctor_user_id: uuid.UUID | None
    service_id: uuid.UUID | None
    service_name: str
    duration_minutes: int
    appointment_date: date
    start_time: str
    end_time: str
    status: str
    is_walk_in: bool
    is_teleconsult: bool
    teleconsult_status: str | None
    notes: str | None
    follow_up_from_visit_id: uuid.UUID | None
    visit_id: uuid.UUID | None
    token_id: uuid.UUID | None
    cancellation_reason: str | None
    created_at: datetime
    patient_name: str | None = None
    patient_uhid: str | None = None
    doctor_name: str | None = None
    department_name: str | None = None

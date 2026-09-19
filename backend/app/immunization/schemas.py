"""Immunization schemas (HD-29)."""
import uuid
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field


class VaccineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    target_disease: str
    standard_doses: int
    min_age_days: int
    max_age_days: int | None
    route: str
    site: str
    dose_quantity: str
    is_active: bool


class ImmunizationRecordCreate(BaseModel):
    patient_id: uuid.UUID
    vaccine_code: str
    dose_number: int = Field(default=1, ge=1)
    administered_at: datetime | None = None
    batch_number: str = Field(..., min_length=1, max_length=50)
    expiry_date: date
    manufacturer: str | None = Field(default=None, max_length=100)
    site: str | None = Field(default=None, max_length=50)
    route: str | None = Field(default=None, max_length=50)
    adverse_reaction: str | None = None
    notes: str | None = None


class ImmunizationRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    vaccine_id: uuid.UUID
    vaccine_code: str
    dose_number: int
    administered_at: datetime
    batch_number: str
    expiry_date: date
    manufacturer: str | None
    site: str | None
    route: str | None
    administered_by: uuid.UUID
    adverse_reaction: str | None
    notes: str | None
    created_at: datetime


class DueVaccineItem(BaseModel):
    vaccine_code: str
    vaccine_name: str
    dose_number: int
    target_disease: str
    min_age_days: int
    status: str  # "due", "upcoming", "overdue"
    due_date: date | None = None


class PatientImmunizationScheduleOut(BaseModel):
    patient_id: uuid.UUID
    patient_name: str
    dob: date | None
    age_days: int | None
    administered: list[ImmunizationRecordOut]
    due: list[DueVaccineItem]


class ImmunizationCertificateOut(BaseModel):
    patient_id: uuid.UUID
    patient_name: str
    dob: date | None
    gender: str | None
    abha_number: str | None
    facility_name: str
    certificate_id: str
    generated_at: datetime
    records: list[ImmunizationRecordOut]

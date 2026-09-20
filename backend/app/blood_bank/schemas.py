"""Pydantic schemas for the blood_bank module (HD-29)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class BloodDonorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_id: uuid.UUID | None = None
    full_name: str = Field(..., min_length=2, max_length=150)
    sex: str | None = None
    dob: date | None = None
    age_years: int | None = Field(default=None, ge=18, le=65)
    blood_group: str = Field(..., description="A+ | A- | B+ | B- | AB+ | AB- | O+ | O-")
    mobile: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    address: str | None = None
    weight_kg: float | None = Field(default=None, ge=30, le=200)
    hemoglobin_g_dl: float | None = Field(default=None, ge=5, le=25)
    last_donation_date: date | None = None
    remarks: str | None = None


class BloodDonorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID | None
    full_name: str
    sex: str | None
    dob: date | None
    age_years: int | None
    blood_group: str
    mobile: str | None
    email: str | None
    weight_kg: float | None
    hemoglobin_g_dl: float | None
    last_donation_date: date | None
    next_eligible_date: date | None
    is_eligible: bool
    remarks: str | None
    created_at: datetime


class BloodUnitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    donor_id: uuid.UUID
    bag_number: str = Field(..., min_length=3, max_length=30)
    blood_group: str
    volume_ml: int = Field(default=450, ge=100, le=1000)
    expiry_date: date
    screening_status: Literal["pending", "passed", "failed"] = "pending"


class BloodUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    donor_id: uuid.UUID
    bag_number: str
    blood_group: str
    volume_ml: int
    collected_at: datetime | None
    expiry_date: date
    screening_status: str
    status: str
    issued_to_patient_id: uuid.UUID | None
    created_at: datetime


class BloodCrossmatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str | None = None
    patient_id: uuid.UUID
    unit_id: uuid.UUID
    compatibility_result: Literal["compatible", "incompatible", "conditional"]
    notes: str | None = None


class BloodCrossmatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    request_id: str | None
    patient_id: uuid.UUID
    unit_id: uuid.UUID
    compatibility_result: str
    crossmatched_by: uuid.UUID
    crossmatched_at: datetime
    issued_at: datetime | None
    adverse_reactions: str | None
    notes: str | None
    created_at: datetime


class BloodIssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    crossmatch_id: uuid.UUID
    adverse_reactions: str | None = None
    notes: str | None = None

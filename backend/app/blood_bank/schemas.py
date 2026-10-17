"""Pydantic schemas for the blood_bank module (HD-29)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.enums import BloodGroup

_RH = {"+": "pos", "POS": "pos", "POSITIVE": "pos", "-": "neg", "NEG": "neg", "NEGATIVE": "neg"}


def normalise_blood_group(value: str | None) -> str | None:
    """"O+", "o pos" and "o_pos" are the same group; the database stores o_pos.

    The donor and stock forms send "O+", which the CHECK refused, so every
    donor registration and every unit added to stock failed as a "conflict"
    (QA 17 Oct 2026).
    """
    if value is None:
        return None
    raw = value.strip().upper().replace(" ", "").replace("_", "")
    for suffix, rh in sorted(_RH.items(), key=lambda kv: -len(kv[0])):
        if raw.endswith(suffix) and raw[: -len(suffix)] in {"A", "B", "AB", "O"}:
            code = f"{raw[: -len(suffix)].lower()}_{rh}"
            if code in BloodGroup.values():
                return code
    raise ValueError("Choose a blood group: A+, A-, B+, B-, AB+, AB-, O+ or O-")


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

    @field_validator("blood_group")
    @classmethod
    def _group(cls, value: str) -> str:
        return normalise_blood_group(value)

    @field_validator("last_donation_date")
    @classmethod
    def _not_future(cls, value: date | None) -> date | None:
        # A future "last donation" was accepted (QA 17 Oct 2026).
        if value is not None and value > datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise ValueError("The last donation date cannot be in the future")
        return value

    @field_validator("mobile")
    @classmethod
    def _mobile_digits(cls, value: str | None) -> str | None:
        # Letters were accepted in the contact phone (QA 17 Oct 2026).
        if value is None or not value.strip():
            return None
        digits = value.strip().replace(" ", "").replace("-", "")
        if digits.startswith("+91"):
            digits = digits[3:]
        if not (len(digits) == 10 and digits.isdigit() and digits[0] in "6789"):
            raise ValueError("Enter a 10-digit mobile number starting with 6, 7, 8 or 9")
        return digits


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

    @field_validator("blood_group")
    @classmethod
    def _group(cls, value: str) -> str:
        return normalise_blood_group(value)


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

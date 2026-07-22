"""Patient request/response schemas — POST /patients (§4.4)."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, model_validator


class PatientCreate(BaseModel):
    full_name: str
    sex: str
    dob: date | None = None
    age_years: int | None = None
    mobile: str | None = None
    abha_number: str | None = None
    facility_id: uuid.UUID

    @model_validator(mode="after")
    def _dob_or_age_required(self) -> "PatientCreate":
        if self.dob is None and self.age_years is None:
            raise ValueError("Either dob or age_years is required")
        return self


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    uhid: str | None
    thid: str | None
    full_name: str
    sex: str
    dob: date | None
    age_years: int | None
    mobile: str | None
    abha_number: str | None
    identity_path: str
    identity_status: str
    photo_file_id: uuid.UUID | None
    facility_id: uuid.UUID
    created_at: datetime

"""Patient request/response schemas — POST /patients (§4.4)."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

class PatientCreate(BaseModel):
    full_name: str
    sex: str
    dob: date | None = None
    age_years: int | None = None
    mobile: str | None = None
    abha_number: str | None = None
    aadhaar_number: str | None = None
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


class PatientSearchRequest(BaseModel):
    full_name: str | None = None
    dob: date | None = None
    mobile: str | None = None
    uhid: str | None = None
    aadhaar_number: str | None = None
    abha_number: str | None = None
    facility_id: uuid.UUID | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def _at_least_one_criterion(self) -> "PatientSearchRequest":
        if not any([self.full_name, self.mobile, self.uhid, self.aadhaar_number, self.abha_number]):
            raise ValueError("At least one search criterion is required")
        return self


class PatientSearchResult(BaseModel):
    id: uuid.UUID
    uhid: str | None
    full_name: str
    sex: str
    age_years: int | None
    mobile_masked: str | None
    match_score: float
    matched_on: str  # "aadhaar" | "abha" | "uhid" | "mobile" | "name_dob"


class PatientSearchResponse(BaseModel):
    items: list[PatientSearchResult]
    page: int
    page_size: int
    total: int
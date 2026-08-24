"""Patient request/response schemas — POST /patients (§4.4)."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _normalise_aadhaar(value: str | None) -> str | None:
    """Return the 12 digits accepted by the blind-index function.

    Formatting spaces and hyphens are harmless and common on paper forms. Any
    other character, or a non-12-digit value, is rejected by Pydantic so it
    cannot become the ValueError/HTTP 500 found by authenticated ZAP.
    """
    if value is None:
        return None
    if any(not (character.isdigit() or character in " -") for character in value):
        raise ValueError("aadhaar_number may contain only digits, spaces and hyphens")
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) != 12:
        raise ValueError("aadhaar_number must contain exactly 12 digits")
    return digits

class PatientCreate(BaseModel):
    full_name: str
    sex: str
    dob: date | None = None
    age_years: int | None = None
    mobile: str | None = None
    abha_number: str | None = None
    aadhaar_number: str | None = None

    _validate_aadhaar = field_validator("aadhaar_number")(_normalise_aadhaar)

    @model_validator(mode="after")
    def _dob_or_age_required(self) -> PatientCreate:
        if self.dob is None and self.age_years is None:
            raise ValueError("Either dob or age_years is required")
        return self


class PatientUpdate(BaseModel):
    """PATCH /patients/{id} — all fields optional, only supplied fields written.

    `reason` is not stored on the patient row — it is forwarded to the
    audit log's `reason` column so reviewers know WHY a field changed,
    not just what changed (schema doc §26.1 Audit Events).
    """
    full_name: str | None = None
    sex: str | None = None
    dob: date | None = None
    age_years: int | None = None
    mobile: str | None = None
    abha_number: str | None = None
    guardian_name: str | None = None
    guardian_relationship: str | None = None
    address_line: str | None = None
    village_town: str | None = None
    district: str | None = None
    state_code: str | None = None
    pincode: str | None = None
    reason: str | None = None  # audit reason, not stored on patient row

    @model_validator(mode="after")
    def _at_least_one_field(self) -> PatientUpdate:
        updateable = (
            "full_name", "sex", "dob", "age_years", "mobile", "abha_number",
            "guardian_name", "guardian_relationship",
            "address_line", "village_town", "district", "state_code", "pincode",
        )
        if not any(getattr(self, f) is not None for f in updateable):
            raise ValueError("At least one patient field must be supplied for update")
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


class PatientDetailOut(PatientOut):
    """PatientOut plus the fields a single-record read needs.

    Kept separate rather than widening PatientOut, which is the response for
    POST and PATCH and is consumed by the registration flow — this is additive
    where it is wanted and unchanged where it is not.

    `row_version` is here because PATCH /patients/{id} increments it for
    optimistic concurrency (0035) and the If-Match check is staged as a
    follow-up. When that lands, the client needs a way to have read the value
    first; without a GET there was none.

    `merged_from_patient_id` is set when the caller asked for an id that has
    since been merged away. The body describes the surviving record, and this
    field says which id was asked for — otherwise a screen would silently show
    a different patient than the one requested.
    """

    status: str
    merged_into_patient_id: uuid.UUID | None = None
    merged_from_patient_id: uuid.UUID | None = None
    row_version: int


class PatientSearchRequest(BaseModel):
    full_name: str | None = None
    dob: date | None = None
    mobile: str | None = None
    uhid: str | None = None
    aadhaar_number: str | None = None
    abha_number: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    _validate_aadhaar = field_validator("aadhaar_number")(_normalise_aadhaar)

    @model_validator(mode="after")
    def _at_least_one_criterion(self) -> PatientSearchRequest:
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

class MergeRequestCreate(BaseModel):
    source_patient_id: uuid.UUID
    target_patient_id: uuid.UUID
    source_type: str  # "thid" | "duplicate_uhid" (MergeSourceType enum)
    reason: str | None = None


class MergeActionRequest(BaseModel):
    reason: str | None = None  # required for reject, optional for approve


class MergeLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: str
    source_patient_id: uuid.UUID
    target_patient_id: uuid.UUID
    requested_by: uuid.UUID
    requested_at: datetime
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    status: str
    reason: str | None
    decision_reason: str | None = None

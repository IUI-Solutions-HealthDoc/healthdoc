"""Emergency registration schemas — THID issuance for unidentified/critical patients."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, model_validator


class EmergencyPatientCreate(BaseModel):
    full_name: str | None = None      # often unknown at arrival
    sex: str
    age_years: int | None = None      # clinician's visual estimate if DOB unknown
    mobile: str | None = None
    facility_id: uuid.UUID

    @model_validator(mode="after")
    def _age_estimate_required(self) -> "EmergencyPatientCreate":
        # patients table CHECK requires dob OR age_years NOT NULL — since dob is
        # essentially never known for an unidentified emergency patient, age_years
        # must be supplied, even as a rough clinical estimate. Confirm with Tech
        # Lead: is a clinician-estimated age acceptable here, or should there be a
        # different fallback (e.g. a sentinel value)?
        if self.age_years is None:
            raise ValueError("age_years (estimate) is required when dob is unknown")
        return self


class EmergencyPatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thid: str
    full_name: str
    sex: str
    age_years: int | None
    identity_path: str
    identity_status: str
    facility_id: uuid.UUID

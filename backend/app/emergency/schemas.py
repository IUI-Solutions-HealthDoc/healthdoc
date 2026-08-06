"""Emergency registration schemas — THID issuance and THID→UHID promotion (W5-01)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator


class EmergencyPatientCreate(BaseModel):
    full_name: str | None = None      # often unknown at arrival
    sex: str
    age_years: int | None = None      # clinician's visual estimate if DOB unknown
    mobile: str | None = None
    # facility_id removed from payload (blocker 3 equivalent) — sourced from
    # current_db_user.facility_id in the router so a nurse at facility A
    # cannot register an emergency patient into facility B.

    @model_validator(mode="after")
    def _age_estimate_required(self) -> "EmergencyPatientCreate":
        if self.age_years is None:
            raise ValueError("age_years (estimate) is required when dob is unknown")
        return self


class EmergencyPatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thid: str | None
    uhid: str | None
    full_name: str
    sex: str
    age_years: int | None
    identity_path: str
    identity_status: str
    facility_id: uuid.UUID


class PromotionRequest(BaseModel):
    """Body for POST /emergency/patients/{id}/promote."""
    reason: str | None = None


class UnmergeRequest(BaseModel):
    """Body for POST /emergency/patients/promotions/{merge_id}/unmerge."""
    reason: str | None = None


class PromotionOut(BaseModel):
    """Response for promote/approve/unmerge endpoints."""
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
    unmerge_reason: str | None

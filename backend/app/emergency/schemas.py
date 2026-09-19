"""Emergency registration schemas — THID issuance and THID→UHID promotion (W5-01)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.common.enums import Sex


class EmergencyPatientCreate(BaseModel):
    full_name: str | None = None      # often unknown at arrival
    sex: str
    age_years: int | None = Field(default=None, ge=0, le=150)
    mobile: str | None = None
    # facility_id removed from payload (blocker 3 equivalent) — sourced from
    # current_db_user.facility_id in the router so a nurse at facility A
    # cannot register an emergency patient into facility B.

    @model_validator(mode="after")
    def _age_estimate_required(self) -> "EmergencyPatientCreate":
        if self.age_years is None:
            raise ValueError("age_years (estimate) is required when dob is unknown")
        if self.sex not in Sex.values():
            raise ValueError(f"sex must be one of: {', '.join(sorted(Sex.values()))}")
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


class EmergencyWorklistItem(BaseModel):
    """Active emergency arrival item for clinicians without requiring an OPD token."""
    model_config = ConfigDict(from_attributes=True)

    visit_id: uuid.UUID
    visit_number: str
    patient_id: uuid.UUID
    thid: str | None = None
    uhid: str | None = None
    full_name: str
    age_years: int | None = None
    sex: str
    arrival_time: datetime
    status: str
    visit_type: str = "emergency"


# ---------------------------------------------------------------------------
# HD-18: ED Triage and Tracking Schemas
# ---------------------------------------------------------------------------

VALID_ACUITIES = {"resuscitation", "emergent", "urgent", "non_urgent"}
VALID_TRIAGE_STATUSES = {"waiting", "in_treatment", "admitted", "discharged", "lwbs"}
VALID_DISPOSITIONS = {"admit", "discharge", "lwbs", "transfer"}


class EmergencyTriageCreate(BaseModel):
    patient_id: uuid.UUID
    visit_id: uuid.UUID
    acuity_level: str = Field(..., description="resuscitation | emergent | urgent | non_urgent")
    chief_complaint: str = Field(..., min_length=1)
    triage_notes: str | None = None
    assigned_doctor_id: uuid.UUID | None = None
    assigned_bay: str | None = None
    triaged_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_acuity(self) -> "EmergencyTriageCreate":
        if self.acuity_level not in VALID_ACUITIES:
            raise ValueError(f"acuity_level must be one of: {', '.join(sorted(VALID_ACUITIES))}")
        return self


class EmergencyTriageUpdate(BaseModel):
    status: str | None = None
    assigned_doctor_id: uuid.UUID | None = None
    assigned_bay: str | None = None
    clinician_seen: bool | None = None
    disposition: str | None = None
    disposition_notes: str | None = None

    @model_validator(mode="after")
    def _validate_update(self) -> "EmergencyTriageUpdate":
        if self.status is not None and self.status not in VALID_TRIAGE_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(VALID_TRIAGE_STATUSES))}")
        if self.disposition is not None and self.disposition not in VALID_DISPOSITIONS:
            raise ValueError(f"disposition must be one of: {', '.join(sorted(VALID_DISPOSITIONS))}")
        return self


class EmergencyReTriageRequest(BaseModel):
    new_acuity: str = Field(..., description="resuscitation | emergent | urgent | non_urgent")
    reason: str = Field(..., min_length=10, description="Mandatory clinical justification for acuity change.")

    @model_validator(mode="after")
    def _validate_re_triage(self) -> "EmergencyReTriageRequest":
        if self.new_acuity not in VALID_ACUITIES:
            raise ValueError(f"new_acuity must be one of: {', '.join(sorted(VALID_ACUITIES))}")
        return self


class EmergencyTriageLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    triage_id: uuid.UUID
    previous_acuity: str
    new_acuity: str
    reason: str
    changed_by: uuid.UUID
    changed_at: datetime


class EmergencyTriageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    facility_id: uuid.UUID
    patient_id: uuid.UUID
    visit_id: uuid.UUID
    acuity_level: str
    chief_complaint: str
    triage_notes: str | None = None
    assigned_doctor_id: uuid.UUID | None = None
    assigned_bay: str | None = None
    status: str
    triaged_at: datetime
    triaged_by: uuid.UUID
    clinician_seen_at: datetime | None = None
    door_to_clinician_minutes: int | None = None
    disposition: str | None = None
    disposition_at: datetime | None = None
    disposition_notes: str | None = None
    created_at: datetime
    patient_name: str | None = None
    patient_identifier: str | None = None
    doctor_name: str | None = None
    logs: list[EmergencyTriageLogOut] = []


class EmergencyMetricsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    active_census: int
    waiting_count: int
    in_treatment_count: int
    resuscitation_count: int
    emergent_count: int
    urgent_count: int
    non_urgent_count: int
    avg_door_to_clinician_minutes: float | None = None
    lwbs_count: int


"""backend/app/encounters/schemas.py -- request/response models for encounter + diagnosis endpoints."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class EncounterCreate(BaseModel):
    visit_id: UUID
    #: The attending clinician, who is NOT necessarily the caller — a nurse may
    #: open the encounter for the doctor about to see the patient. Still sent by
    #: the client, but now validated as an active user of the caller's facility
    #: rather than trusted (service._assert_provider_in_facility).
    provider_user_id: UUID
    #: Ignored. Kept only so existing clients do not break on an unexpected
    #: field; the value written is always the authenticated caller. It was
    #: REQUIRED and written straight through — see service.create_encounter.
    created_by: UUID | None = None
    encounter_type: str | None = None
    chief_complaint: str | None = None
    started_at: datetime | None = None


class EncounterUpdate(BaseModel):
    #: Ignored — the token supplies it. Was required AND assigned
    #: unconditionally, so omitting it NULLed the last-editor of the note.
    updated_by: UUID | None = None
    encounter_type: str | None = None
    chief_complaint: str | None = None
    ended_at: datetime | None = None
    subjective: str | None = None
    objective: str | None = None
    assessment: str | None = None
    plan: str | None = None
    note_status: str | None = Field(default=None, description="pending | stored | failed")


class EncounterOut(BaseModel):
    id: UUID
    visit_id: UUID
    provider_user_id: UUID
    encounter_type: str | None
    chief_complaint: str | None
    started_at: datetime | None
    ended_at: datetime | None
    subjective: str | None
    objective: str | None
    assessment: str | None
    plan: str | None
    note_status: str
    row_version: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class DiagnosisCreate(BaseModel):
    encounter_id: UUID
    #: Ignored. Kept only so existing clients do not break on an unexpected
    #: field; the value written is always the authenticated caller. It was
    #: REQUIRED and written straight through — see service.create_diagnosis.
    created_by: UUID | None = None
    icd_code: str
    icd_version: str
    icd_code_id: UUID | None = None
    icd_uri: str | None = None
    post_coordinated_code: str | None = None
    diagnosis_text: str
    diagnosis_type: str = Field(..., description="provisional | final | differential")
    is_primary: bool = False


class DiagnosisOut(BaseModel):
    id: UUID
    encounter_id: UUID
    icd_code: str
    icd_version: str
    icd_code_id: UUID | None
    icd_uri: str | None
    post_coordinated_code: str | None
    diagnosis_text: str
    diagnosis_type: str
    is_primary: bool
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class DoctorReviewCreate(BaseModel):
    lab_order_item_id: UUID | None = None
    radiology_order_item_id: UUID | None = None
    notes: str | None = None


class DoctorReviewStatusUpdate(BaseModel):
    status: str = Field(..., description="reviewed | signed_off")
    notes: str | None = None


class DoctorReviewOut(BaseModel):
    id: UUID
    encounter_id: UUID
    reviewed_by: UUID
    lab_order_item_id: UUID | None
    radiology_order_item_id: UUID | None
    status: str
    notes: str | None
    signed_off_at: datetime | None
    created_at: datetime
    updated_at: datetime
    #: The reviewer's name: "Signed off by 29ef040e-…" (QA 16 Oct 2026).
    reviewed_by_name: str | None = None
    model_config = {"from_attributes": True}

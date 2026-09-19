"""Pydantic schemas for Operation Theatre (OT) scheduling, WHO surgical safety checklist, and operative records (HD-27)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

OtCaseStatus = Literal["scheduled", "in_progress", "completed", "cancelled"]


class OtScheduleCreate(BaseModel):
    patient_id: uuid.UUID
    visit_id: uuid.UUID
    theatre_number: str = Field(default="OT-1", max_length=50)
    scheduled_start: datetime
    scheduled_end: datetime
    procedure_name: str = Field(..., min_length=1)
    admission_id: uuid.UUID | None = None
    pre_op_checklist: dict[str, Any] | None = None


class WhoSafetyChecklistUpdate(BaseModel):
    sign_in_confirmed: bool = Field(
        ...,
        description="Phase 1 (Before induction): Patient identity, surgical site, consent, pulse ox, allergy & airway check.",
    )
    time_out_confirmed: bool = Field(
        ...,
        description="Phase 2 (Before skin incision): Team introductions, operative review, antibiotic prophylaxis, imaging.",
    )
    sign_out_confirmed: bool = Field(
        ...,
        description="Phase 3 (Before patient leaves room): Name of procedure, sponge/needle/instrument counts, specimen labelling.",
    )
    confirmed_by_role: str = Field(
        default="circulating_nurse",
        description="Role performing checklist verification (e.g. circulating_nurse, surgeon, anesthetist).",
    )
    notes: str | None = None


class OtScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    facility_id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str | None = None
    patient_uhid: str | None = None
    visit_id: uuid.UUID
    theatre_number: str
    scheduled_start: datetime
    scheduled_end: datetime
    procedure_name: str
    status: OtCaseStatus
    admission_id: uuid.UUID | None = None
    pre_op_checklist: dict[str, Any] | None = None
    cancel_reason: str | None = None
    surgical_safety_confirmed: bool = False
    created_at: datetime


class OtScheduleCancelRequest(BaseModel):
    cancel_reason: str = Field(..., min_length=1)


class OtRecordCreate(BaseModel):
    started_at: datetime
    ended_at: datetime | None = None
    surgeon_user_id: uuid.UUID
    anesthetist_user_id: uuid.UUID | None = None
    notes: str | None = None
    pre_op_diagnosis: str | None = None
    post_op_diagnosis: str | None = None
    procedure_performed: str | None = None
    anesthesia_type: str | None = None
    scrub_nurse: str | None = None
    circulating_nurse: str | None = None
    implants_used: list[dict[str, Any]] | dict[str, Any] | None = None
    sponge_needle_count_correct: bool = True
    specimens_sent: list[dict[str, Any]] | dict[str, Any] | None = None
    complications: str | None = None
    recovery_status: str | None = None


class OtRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ot_schedule_id: uuid.UUID
    started_at: datetime | None
    ended_at: datetime | None
    surgeon_user_id: uuid.UUID
    anesthetist_user_id: uuid.UUID | None
    notes: str | None
    pre_op_diagnosis: str | None
    post_op_diagnosis: str | None
    procedure_performed: str | None
    anesthesia_type: str | None
    scrub_nurse: str | None
    circulating_nurse: str | None
    implants_used: Any | None
    sponge_needle_count_correct: bool | None
    specimens_sent: Any | None
    complications: str | None
    recovery_status: str | None
    created_at: datetime


class OtScheduleDetailOut(OtScheduleOut):
    record: OtRecordOut | None = None

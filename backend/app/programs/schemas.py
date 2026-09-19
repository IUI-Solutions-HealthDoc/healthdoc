"""Pydantic schemas for longitudinal care programs and condition registries (HD-28)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CareProgramOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    program_code: str
    program_name: str
    category: str
    description: str | None = None
    is_active: bool


class ProgramEnrolmentCreate(BaseModel):
    patient_id: uuid.UUID
    program_code: str = Field(..., description="Program code e.g. DIABETES_T2, HYPERTENSION, ANC_MATERNAL, CKD_RENAL")
    enrolment_date: date | None = None
    target_outcomes: dict[str, Any] | None = Field(
        default=None,
        description="Target clinical indicators e.g. {'target_hba1c': 7.0, 'target_systolic': 130, 'target_diastolic': 80}",
    )


class ProgramEnrolmentExitRequest(BaseModel):
    exit_date: date = Field(default_factory=date.today)
    exit_reason: str = Field(..., min_length=1, description="Clinical reason for discharge or program exit.")


class ProgramEnrolmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    facility_id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str | None = None
    patient_uhid: str | None = None
    program_code: str
    program_name: str
    enrolment_date: date
    status: str
    exit_date: date | None = None
    exit_reason: str | None = None
    target_outcomes: dict[str, Any] | None = None
    enrolled_by: uuid.UUID
    created_at: datetime


class ProgramVisitCreate(BaseModel):
    scheduled_date: date
    completed_date: date | None = None
    metrics: dict[str, Any] | None = Field(
        default=None,
        description="Clinical indicators recorded e.g. {'hba1c': 7.2, 'bp_systolic': 128, 'bp_diastolic': 82, 'weight_kg': 74.5}",
    )
    clinical_summary: str | None = None


class ProgramVisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    enrolment_id: uuid.UUID
    scheduled_date: date
    completed_date: date | None = None
    status: str
    metrics: dict[str, Any] | None = None
    clinical_summary: str | None = None
    conducted_by: uuid.UUID | None = None
    created_at: datetime


class ProgramTimelineOut(BaseModel):
    enrolment: ProgramEnrolmentOut
    visits: list[ProgramVisitOut]

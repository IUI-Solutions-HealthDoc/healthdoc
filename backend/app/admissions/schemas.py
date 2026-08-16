"""backend/app/admissions/schemas.py -- request/response models for #216
(B3-W5-01): IPD admission and transfers. Discharge schemas land in the
follow-up PR that adds discharge_patient()."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AdmissionCreate(BaseModel):
    visit_id: UUID
    ward_id: UUID
    bed_id: UUID
    reason: str | None = None
    admitted_at: datetime | None = None


class AdmissionOut(BaseModel):
    id: UUID
    visit_id: UUID
    patient_id: UUID
    ward_id: UUID
    bed_id: UUID
    admitted_at: datetime
    reason: str | None
    status: str
    model_config = {"from_attributes": True}


class TransferRequest(BaseModel):
    to_ward_id: UUID
    to_bed_id: UUID
    reason: str | None = None


class DischargeRequest(BaseModel):
    discharge_type: str = Field(..., description="discharged | dama | deceased | absconded | transferred")
    discharge_summary: str | None = None
    follow_up_date: date | None = None
    destination_facility_id: UUID | None = None
    destination_facility_name: str | None = None
    discharged_at: datetime | None = None


class DischargeOut(BaseModel):
    id: UUID
    admission_id: UUID
    discharged_at: datetime
    discharge_type: str
    discharge_summary: str | None
    follow_up_date: date | None
    destination_facility_id: UUID | None
    destination_facility_name: str | None
    model_config = {"from_attributes": True}


class MovementOut(BaseModel):
    id: UUID
    admission_id: UUID
    from_ward_id: UUID | None
    from_bed_id: UUID | None
    to_ward_id: UUID
    to_bed_id: UUID
    moved_at: datetime
    reason: str | None
    model_config = {"from_attributes": True}


class DischargeSummaryOut(BaseModel):
    admission: AdmissionOut
    discharge: DischargeOut | None
    movements: list[MovementOut]

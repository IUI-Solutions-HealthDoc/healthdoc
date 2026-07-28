import uuid
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field


class AdmissionCreate(BaseModel):
    visit_id: uuid.UUID
    patient_id: uuid.UUID
    ward_id: uuid.UUID
    bed_id: uuid.UUID
    admitted_at: datetime
    reason: Optional[str] = None


class AdmissionOut(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    patient_id: uuid.UUID
    ward_id: uuid.UUID
    bed_id: uuid.UUID
    admitted_at: datetime
    status: str
    reason: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class TransferCreate(BaseModel):
    to_ward_id: uuid.UUID
    to_bed_id: uuid.UUID
    reason: Optional[str] = None


class TransferOut(BaseModel):
    id: uuid.UUID
    admission_id: uuid.UUID
    from_ward_id: Optional[uuid.UUID]
    from_bed_id: Optional[uuid.UUID]
    to_ward_id: uuid.UUID
    to_bed_id: uuid.UUID
    moved_at: datetime
    reason: Optional[str]

    model_config = {"from_attributes": True}


class DischargeCreate(BaseModel):
    discharge_type: str  # validated against DischargeType enum in service layer
    discharge_summary: Optional[str] = None
    follow_up_date: Optional[date] = None


class DischargeOut(BaseModel):
    id: uuid.UUID
    admission_id: uuid.UUID
    discharged_at: datetime
    discharge_type: str
    follow_up_date: Optional[date]
    created_at: datetime

    model_config = {"from_attributes": True}
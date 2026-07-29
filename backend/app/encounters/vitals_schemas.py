import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class VitalsCreate(BaseModel):
    encounter_id: Optional[uuid.UUID] = None
    admission_id: Optional[uuid.UUID] = None
    patient_id: uuid.UUID

    height_cm: Optional[Decimal] = None
    weight_kg: Optional[Decimal] = None
    waist_cm: Optional[Decimal] = None
    hip_cm: Optional[Decimal] = None

    temp_c: Optional[Decimal] = None
    pulse_bpm: Optional[int] = None
    resp_rate: Optional[int] = None
    bp_systolic: Optional[int] = None
    bp_diastolic: Optional[int] = None
    spo2_pct: Optional[int] = Field(default=None, ge=0, le=100)
    pain_score: Optional[int] = Field(default=None, ge=0, le=10)

    # NOTE: bmi and whr are intentionally absent -- app-computed only,
    # never accepted from the client (schema doc §3-0023).


class VitalsOut(BaseModel):
    id: uuid.UUID
    encounter_id: Optional[uuid.UUID]
    admission_id: Optional[uuid.UUID]
    patient_id: uuid.UUID
    measured_at: datetime

    height_cm: Optional[Decimal]
    weight_kg: Optional[Decimal]
    bmi: Optional[Decimal]
    waist_cm: Optional[Decimal]
    hip_cm: Optional[Decimal]
    whr: Optional[Decimal]

    temp_c: Optional[Decimal]
    pulse_bpm: Optional[int]
    resp_rate: Optional[int]
    bp_systolic: Optional[int]
    bp_diastolic: Optional[int]
    spo2_pct: Optional[int]
    pain_score: Optional[int]

    created_by: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class VitalsCreate(BaseModel):
    encounter_id: uuid.UUID
    recorded_by: uuid.UUID
    bp_systolic: Optional[int] = None
    bp_diastolic: Optional[int] = None
    pulse: Optional[int] = None
    temperature: Optional[Decimal] = None
    spo2: Optional[int] = Field(default=None, ge=0, le=100)
    respiratory_rate: Optional[int] = None
    weight: Optional[Decimal] = None
    height: Optional[Decimal] = None


class VitalsOut(BaseModel):
    id: uuid.UUID
    encounter_id: uuid.UUID
    bp_systolic: Optional[int]
    bp_diastolic: Optional[int]
    pulse: Optional[int]
    temperature: Optional[Decimal]
    spo2: Optional[int]
    respiratory_rate: Optional[int]
    weight: Optional[Decimal]
    height: Optional[Decimal]
    recorded_at: datetime
    recorded_by: uuid.UUID

    model_config = ConfigDict(from_attributes=True)

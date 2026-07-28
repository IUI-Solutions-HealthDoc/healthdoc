import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class HandoverNoteCreate(BaseModel):
    admission_id: uuid.UUID
    shift: str
    situation: Optional[str] = None
    background: Optional[str] = None
    assessment: Optional[str] = None
    recommendation: Optional[str] = None
    handed_over_to: uuid.UUID


class HandoverNoteOut(BaseModel):
    id: uuid.UUID
    admission_id: uuid.UUID
    shift: str
    situation: Optional[str]
    background: Optional[str]
    assessment: Optional[str]
    recommendation: Optional[str]
    handed_over_to: uuid.UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class IntakeOutputCreate(BaseModel):
    admission_id: uuid.UUID
    recorded_at: datetime
    entry_type: str
    volume_ml: int
    notes: Optional[str] = None


class IntakeOutputOut(BaseModel):
    id: uuid.UUID
    admission_id: uuid.UUID
    recorded_at: datetime
    entry_type: str
    volume_ml: int
    notes: Optional[str]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

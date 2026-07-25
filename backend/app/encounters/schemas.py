import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class EncounterCreate(BaseModel):
    visit_id: uuid.UUID
    provider_user_id: uuid.UUID
    created_by: uuid.UUID
    encounter_type: Optional[str] = None
    chief_complaint: Optional[str] = None


class EncounterUpdate(BaseModel):
    chief_complaint: Optional[str] = None
    ended_at: Optional[datetime] = None
    subjective: Optional[str] = None
    objective: Optional[str] = None
    assessment: Optional[str] = None
    plan: Optional[str] = None


class EncounterOut(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    provider_user_id: uuid.UUID
    encounter_type: Optional[str]
    chief_complaint: Optional[str]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    subjective: Optional[str] = None
    objective: Optional[str] = None
    assessment: Optional[str] = None
    plan: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)

import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class AllergyCreate(BaseModel):
    allergen: str
    reaction: Optional[str] = None
    severity: Optional[str] = None
    created_by: uuid.UUID


class AllergyOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    allergen: str
    reaction: Optional[str]
    severity: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

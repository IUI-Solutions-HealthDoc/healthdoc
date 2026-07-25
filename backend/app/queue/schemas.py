import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class QueueEntry(BaseModel):
    visit_id: uuid.UUID
    visit_number: str
    patient_id: uuid.UUID
    patient_name: str
    uhid: Optional[str]
    visit_status: str
    visit_date: datetime
    encounter_id: Optional[uuid.UUID] = None
    provider_user_id: Optional[uuid.UUID] = None
    chief_complaint: Optional[str] = None
    started_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class NotificationHistoryCreate(BaseModel):
    user_id: uuid.UUID
    channel: str
    payload: dict


class NotificationHistoryOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    channel: str
    payload: dict
    status: str
    sent_at: datetime

    model_config = ConfigDict(from_attributes=True)

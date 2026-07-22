import uuid
from datetime import date
from pydantic import BaseModel, ConfigDict


class QueueCreate(BaseModel):
    department_id: uuid.UUID
    doctor_user_id: uuid.UUID
    room_id: uuid.UUID | None
    display_label: str | None
    service_date: date


class QueueOut(BaseModel):
    id: uuid.UUID
    department_id: uuid.UUID
    doctor_user_id: uuid.UUID
    room_id: uuid.UUID | None
    display_label: str | None
    service_date: date
    is_open: bool

    model_config = ConfigDict(from_attributes=True)


class QueueTokenCreate(BaseModel):
    queue_id: uuid.UUID
    visit_id: uuid.UUID | None
    sequence: int
    token_display: str


class QueueTokenOut(BaseModel):
    id: uuid.UUID
    queue_id: uuid.UUID
    visit_id: uuid.UUID | None
    sequence: int
    token_display: str
    status: str
    priority: str

    model_config = ConfigDict(from_attributes=True)

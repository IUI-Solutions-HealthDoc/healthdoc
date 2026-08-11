import uuid
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict
from app.common.enums import QueuePriority


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
    created_at: datetime
    called_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

class QueueTokenGenerateRequest(BaseModel):
    """visit_id is required — complete_by_visit_id() needs it to trigger
    automatic call-next."""
    queue_id: uuid.UUID
    visit_id: uuid.UUID
    priority: str = QueuePriority.NORMAL.value


class TokenPriorityElevate(BaseModel):
    priority: str
    reason: str

class QueueTokenListItemOut(QueueTokenOut):
    doctor_name: str
    room_number: str | None
    model_config = ConfigDict(from_attributes=True)
 
 
class QueueTokenListOut(BaseModel):
    waiting_count: int
    now_serving: str | None
    items: list[QueueTokenListItemOut]
 
 
class CompleteAdvanceOut(BaseModel):
    completed_token: QueueTokenOut
    next_token: QueueTokenOut | None
    

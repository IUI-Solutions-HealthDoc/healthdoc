import uuid
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict

from app.common.enums import ResultStatus


class ResultCreate(BaseModel):
    order_id: uuid.UUID
    created_by: uuid.UUID
    result_status: ResultStatus = ResultStatus.PENDING
    result_text: Optional[str] = None
    result_data: Optional[dict[str, Any]] = None
    performed_by: Optional[uuid.UUID] = None
    performed_at: Optional[datetime] = None


class ResultReview(BaseModel):
    reviewed_by: uuid.UUID
    review_notes: Optional[str] = None
    result_status: Optional[ResultStatus] = None
    is_signed_off: bool = True


class ResultOut(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    result_status: str
    result_text: Optional[str]
    result_data: Optional[dict[str, Any]]
    performed_by: Optional[uuid.UUID]
    performed_at: Optional[datetime]
    reviewed_by: Optional[uuid.UUID]
    reviewed_at: Optional[datetime]
    review_notes: Optional[str]
    is_signed_off: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

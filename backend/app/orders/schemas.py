import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from app.common.enums import OrderType, OrderPriority, OrderStatus


class OrderCreate(BaseModel):
    encounter_id: uuid.UUID
    patient_id: uuid.UUID
    created_by: uuid.UUID
    order_type: OrderType
    priority: OrderPriority = OrderPriority.ROUTINE


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


class OrderOut(BaseModel):
    id: uuid.UUID
    order_number: str
    encounter_id: uuid.UUID
    patient_id: uuid.UUID
    order_type: str
    priority: str
    status: str
    ordered_at: datetime

    model_config = ConfigDict(from_attributes=True)

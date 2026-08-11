"""backend/app/orders/schemas.py -- request/response models for order creation. Field names match DB columns (schema doc §4.2)."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    encounter_id: UUID
    patient_id: UUID
    created_by: UUID
    order_type: str = Field(..., description="lab | radiology | pharmacy | procedure | blood")
    priority: str = Field(default="routine", description="routine | urgent | stat")
    ordered_at: datetime | None = None


class OrderOut(BaseModel):
    id: UUID
    order_number: str
    encounter_id: UUID
    patient_id: UUID
    facility_id: UUID
    order_type: str
    priority: str
    status: str
    ordered_at: datetime
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

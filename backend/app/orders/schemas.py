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


class PrescriptionItemCreate(BaseModel):
    medicine_item_id: UUID | None = None
    medicine_name: str
    dosage: str | None = None
    frequency: str | None = None
    duration_days: int | None = None
    route: str | None = None
    instructions: str | None = None


class PrescriptionCreate(BaseModel):
    encounter_id: UUID
    notes: str | None = None
    items: list[PrescriptionItemCreate]


class PrescriptionItemOut(BaseModel):
    id: UUID
    prescription_id: UUID
    medicine_item_id: UUID | None
    medicine_name: str
    dosage: str | None
    frequency: str | None
    duration_days: int | None
    route: str | None
    instructions: str | None
    status: str
    allergy_override_reason: str | None
    allergy_override_by: UUID | None
    model_config = {"from_attributes": True}


class PrescriptionOut(BaseModel):
    id: UUID
    encounter_id: UUID
    facility_id: UUID
    patient_id: UUID
    notes: str | None
    created_at: datetime
    updated_at: datetime
    items: list[PrescriptionItemOut]
    model_config = {"from_attributes": True}

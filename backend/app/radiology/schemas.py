"""
Request/response shapes for the radiology API (#203).
Mirrors pathology/schemas.py pattern - snake_case, id + accession_number both returned.
"""
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class RadiologyOrderItemCreate(BaseModel):
    """Body for POST /radiology/order-items"""
    modality: str
    scan_type: str
    machine_id: str | None = None


class RadiologyOrderItemOut(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    accession_number: str
    modality: str
    scan_type: str
    machine_id: str | None
    pacs_study_uid: str | None
    scheduled_at: datetime | None
    scan_completed_at: datetime | None = None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScheduleRequest(BaseModel):
    """Body for PUT /radiology/order-items/{item_id}/schedule"""
    scheduled_at: datetime
    machine_id: str


class ScanCompletionRequest(BaseModel):
    """Body for PUT /radiology/order-items/{item_id}/scan-complete"""
    completed_at: datetime | None = None


class RadiologyOrderItemListOut(BaseModel):
    items: list[RadiologyOrderItemOut]
    page: int
    page_size: int
    total: int


class RadiologyReportCreate(BaseModel):
    """Body for POST /radiology/order-items/{item_id}/reports (radiologist draft)."""
    findings: str
    impression: str
    pacs_study_uid: str | None = None


class RadiologyReportSignOff(BaseModel):
    """Body for PUT /radiology/order-items/{item_id}/reports/sign-off"""
    findings: str | None = None
    impression: str | None = None


class RadiologyReportOut(BaseModel):
    id: uuid.UUID
    radiology_order_item_id: uuid.UUID
    version: int
    is_current: bool
    findings: str
    impression: str
    status: str
    created_by: uuid.UUID
    created_at: datetime
    tat_minutes: int | None = None

    model_config = ConfigDict(from_attributes=True)

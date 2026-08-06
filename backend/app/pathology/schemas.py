"""
Request/response shapes for the lab API (#166, #184, #218).
JSON field names = column names, snake_case, no renaming layer (Master Schema §4.2).
"""
import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class LabOrderItemCreate(BaseModel):
    """Body for POST /pathology/order-items"""
    test_code: str | None = None
    test_name: str
    sample_type: str
    department_id: uuid.UUID | None = None
    estimated_minutes: int | None = None


class LabOrderItemOut(BaseModel):
    """Response shape - always includes id AND the business identifier (accession_number)."""
    id: uuid.UUID
    order_id: uuid.UUID
    accession_number: str
    test_code: str | None
    test_name: str
    sample_type: str
    barcode: str | None = None
    collected_at: datetime | None = None
    department_id: uuid.UUID | None
    status: str
    estimated_minutes: int | None
    created_at: datetime

    class Config:
        from_attributes = True


class SampleCollectionRequest(BaseModel):
    """Body for PUT /pathology/order-items/{id}/sample-collection"""
    barcode: str = Field(..., min_length=1, max_length=50)
    collected_at: datetime | None = None


class LabOrderItemListOut(BaseModel):
    """Matches the shared list-endpoint shape (Master Schema §4.3)."""
    items: list[LabOrderItemOut]
    page: int
    page_size: int
    total: int


class LabResultCreate(BaseModel):
    """Body for POST /pathology/order-items/{item_id}/results (technician entry)."""
    result_data: dict
    remarks: str | None = None


class LabResultVerify(BaseModel):
    """Body for PUT /pathology/order-items/{item_id}/results/verify (pathologist approval)."""
    result_data: dict | None = None
    remarks: str | None = None


class LabResultAmend(BaseModel):
    """Body for PUT /pathology/order-items/{item_id}/results/amend (#218)."""
    result_data: dict | None = None
    remarks: str | None = None
    amendment_reason: str = Field(..., min_length=1)


class LabResultOut(BaseModel):
    id: uuid.UUID
    lab_order_item_id: uuid.UUID
    version: int
    is_current: bool
    result_data: dict
    remarks: str | None
    amendment_reason: str | None = None
    status: str
    created_by: uuid.UUID
    created_at: datetime
    tat_minutes: int | None = None

    class Config:
        from_attributes = True


class LabResultHistoryOut(BaseModel):
    """Response for GET /pathology/order-items/{item_id}/results/history (#218)."""
    items: list[LabResultOut] 

class TATByTestOut(BaseModel):
    test_name: str
    sample_count: int
    avg_tat_minutes: float | None
    median_tat_minutes: float | None


class StatusCountOut(BaseModel):
    status: str
    count: int


class PanicFrequencyOut(BaseModel):
    test_name: str
    critical_count: int
    total_count: int
    panic_rate_pct: float


class LabMISSummaryOut(BaseModel):
    """Response for GET /pathology/mis/summary (#231)."""
    date_from: datetime
    date_to: datetime
    tat_by_test: list[TATByTestOut]
    order_counts_by_status: list[StatusCountOut]
    total_orders: int
    total_results: int
    panic_frequency: list[PanicFrequencyOut]

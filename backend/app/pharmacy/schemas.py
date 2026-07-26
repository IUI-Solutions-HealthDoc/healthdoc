from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class PrescriptionQueueItem(BaseModel):
    prescription_id: UUID
    patient_id: UUID
    patient_full_name: str
    uhid: str | None = None
    thid: str | None = None
    visit_id: UUID | None = None
    encounter_id: UUID
    prescribed_at: datetime
    item_count: int
    dispense_status: str | None = None  


class PrescriptionQueueResponse(BaseModel):
    items: list[PrescriptionQueueItem]
    page: int
    page_size: int
    total: int


class BatchAvailability(BaseModel):
    batch_id: UUID
    batch_number: str
    expiry_date: str  # ISO date
    quantity: Decimal
    stock_location_id: UUID
    issue_rate_mrp: Decimal | None = None


class MedicineSearchResult(BaseModel):
    item_id: UUID
    name: str
    generic_name: str | None = None
    strength: str | None = None
    form: str | None = None
    is_controlled_drug: bool
    total_available_quantity: Decimal
    batches: list[BatchAvailability] = Field(
        default_factory=list,
        description="FEFO-ordered (earliest expiry first); only quantity > 0 batches",
    )


class MedicineSearchResponse(BaseModel):
    items: list[MedicineSearchResult]


class DispenseItemCreate(BaseModel):
    prescription_item_id: UUID
    batch_id: UUID
    quantity_dispensed: Decimal = Field(gt=0)
    is_substitute: bool = False
    substitute_reason: str | None = None


class DispenseCreate(BaseModel):
    prescription_id: UUID
    items: list[DispenseItemCreate] = Field(min_length=1)


class DispenseItemOut(BaseModel):
    id: UUID
    prescription_item_id: UUID
    batch_id: UUID
    quantity_prescribed: Decimal | None = None
    quantity_dispensed: Decimal | None = None
    is_substitute: bool
    substitute_reason: str | None = None


class DispenseOut(BaseModel):
    id: UUID
    prescription_id: UUID
    visit_id: UUID | None = None
    status: str
    dispensed_by: UUID
    version: int
    is_current: bool
    created_at: datetime
    items: list[DispenseItemOut]

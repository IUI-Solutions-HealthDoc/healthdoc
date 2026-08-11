from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Prescription queue (GET /pharmacy/queue)
# ---------------------------------------------------------------------------

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
    dispense_status: str | None = None  # None = never dispensed against yet


class PrescriptionQueueResponse(BaseModel):
    items: list[PrescriptionQueueItem]
    page: int
    page_size: int
    total: int


# ---------------------------------------------------------------------------
# Medicine search (GET /pharmacy/medicines/search)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Dispense create (POST /pharmacy/dispenses)
# ---------------------------------------------------------------------------

class DispenseItemCreate(BaseModel):
    prescription_item_id: UUID
    quantity_dispensed: Decimal = Field(gt=0, description="Requested quantity")
    batch_id: UUID | None = Field(
        default=None,
        description="Manual batch pin (W2 behavior). Omit to auto-select via FEFO "
        "(W3), splitting across batches if needed.",
    )
    substitute_item_id: UUID | None = Field(
        default=None,
        description="A different inventory_items.id than what was prescribed. "
        "Requires doctor approval (see POST .../approve) before stock is touched.",
    )
    substitute_reason: str | None = None
    expiry_override: bool = Field(
        default=False,
        description="Required (with expiry_override_reason) to dispense an explicitly "
        "pinned batch that has passed its expiry date. FEFO auto-selection never "
        "picks an expired batch, so this only applies to manual batch_id pins.",
    )
    expiry_override_reason: str | None = Field(
        default=None,
        description="Required when expiry_override is true.",
    )


class DispenseCreate(BaseModel):
    prescription_id: UUID
    items: list[DispenseItemCreate] = Field(min_length=1)
    allow_partial: bool = Field(
        default=False,
        description="If true and available stock < requested for an item, dispense "
        "whatever is available instead of rejecting the whole request.",
    )


class BatchAllocation(BaseModel):
    """One (batch, quantity) slice of a possibly FEFO-split item fulfillment."""
    batch_id: UUID
    batch_number: str
    quantity_from_batch: Decimal
    expiry_date: str


class DispenseItemOut(BaseModel):
    item_row_ids: list[UUID] = Field(
        description="pharmacy_dispense_items.id for each batch used to fulfill this "
        "item — more than one if FEFO split across batches. Empty if this is a "
        "pending substitution (no batch chosen yet)."
    )
    prescription_item_id: UUID
    quantity_prescribed: Decimal | None = None
    quantity_dispensed: Decimal
    is_substitute: bool
    substitute_item_id: UUID | None = None
    substitute_reason: str | None = None
    is_partial: bool = Field(description="quantity_dispensed < quantity_prescribed")
    approval_status: str = Field(
        default="not_required",
        description="not_required | pending | approved | rejected — only substituted "
        "items are ever anything other than not_required",
    )
    batches: list[BatchAllocation] = Field(
        default_factory=list, description="Which batch(es) fulfilled this item, FEFO order"
    )


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


# ---------------------------------------------------------------------------
# Substitution approval (POST /pharmacy/dispenses/{id}/items/{item_id}/approve)
# ---------------------------------------------------------------------------

class SubstitutionApprovalRequest(BaseModel):
    approved: bool
    rejection_reason: str | None = Field(
        default=None, description="Required if approved=false"
    )
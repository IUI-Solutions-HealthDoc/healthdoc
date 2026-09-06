from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

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
    #: The key the allergy check matches on. Null means the check cannot run
    #: for this item — reported as 'uncheckable', never as 'clear'.
    ingredient_code: str | None = None
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
    allergy_override_reason: str | None = Field(
        default=None,
        description="Required (min 20 chars) to dispense an item matching an active patient allergy. Anaphylaxis-severity matches can never be overridden.",
    )
    interaction_override_reason: str | None = Field(
        default=None,
        description="Required (min 20 chars) to dispense an item with a known interaction against another item in the same request. Contraindicated-severity pairs can never be overridden.",
    )

    @model_validator(mode="after")
    def validate_substitution(self) -> "DispenseItemCreate":
        if self.substitute_item_id is not None and not (self.substitute_reason or "").strip():
            raise ValueError("substitute_reason is required when substitute_item_id is provided")
        if self.expiry_override and not (self.expiry_override_reason or "").strip():
            raise ValueError("expiry_override_reason is required when expiry_override is true")
        return self


class DispenseCreate(BaseModel):
    prescription_id: UUID
    items: list[DispenseItemCreate] = Field(min_length=1)
    allow_partial: bool = Field(
        default=False,
        description="If true and available stock < requested for an item, dispense "
        "whatever is available instead of rejecting the whole request.",
    )

    @model_validator(mode="after")
    def reject_duplicate_prescription_items(self) -> "DispenseCreate":
        item_ids = [item.prescription_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("Each prescription item may appear only once in a dispense")
        return self


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

    @model_validator(mode="after")
    def validate_rejection_reason(self) -> "SubstitutionApprovalRequest":
        if not self.approved and not (self.rejection_reason or "").strip():
            raise ValueError("rejection_reason is required when rejecting a substitution")
        return self


class PendingSubstitutionOut(BaseModel):
    item_id: UUID
    dispense_id: UUID
    prescription_id: UUID
    prescription_item_id: UUID
    patient_id: UUID
    patient_full_name: str
    uhid: str | None = None
    prescribed_medicine_name: str
    substitute_item_id: UUID
    substitute_medicine_name: str
    substitute_strength: str | None = None
    substitute_form: str | None = None
    quantity_requested: Decimal
    substitute_reason: str
    requested_at: datetime


class PendingSubstitutionResponse(BaseModel):
    items: list[PendingSubstitutionOut]
    total: int
# ---------------------------------------------------------------------------
# Pharmacy MIS report (GET /pharmacy/mis)
# ---------------------------------------------------------------------------

class PharmacyMisReport(BaseModel):
    facility_id: UUID
    period_start: date
    period_end: date

    prescriptions_total: int
    dispenses_total: int
    fill_rate_pct: Decimal = Field(
        description="dispensed-status dispenses / prescriptions_total; 0 when "
        "prescriptions_total is 0"
    )
    stockout_count: int = Field(
        description="dispenses with status='out_of_stock' in the period"
    )
    substitution_count: int = Field(
        description="pharmacy_dispense_items rows with is_substitute=true in the period"
    )
    substitution_rate_pct: Decimal = Field(
        description="substitution_count / dispenses_total; 0 when dispenses_total is 0"
    )
    avg_turnaround_minutes: Decimal | None = Field(
        default=None,
        description="avg minutes between prescription creation and its first dispense "
        "(version=1) in the period; null when no first-dispenses fall in the period",
    )
    expiring_batches_count: int = Field(
        description="inventory_batches with quantity > 0 expiring within "
        "expiry_window_days of period_end, at this facility's stock locations - "
        "a live snapshot, not period-scoped like the fields above"
    )
    expiring_stock_value: Decimal = Field(
        description="sum(quantity * issue_rate_mrp) for those same expiring batches; "
        "a NULL issue_rate_mrp counts in expiring_batches_count but contributes 0 here"
    )


# -- B6-W5-01: Inventory (GRN, Indent, Adjustment) --------------------------

class GrnItemCreate(BaseModel):
    item_id: UUID
    batch_number: str | None = Field(default=None, min_length=1, max_length=50)
    expiry_date: date | None = None
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)


class GrnCreate(BaseModel):
    supplier_id: UUID
    purchase_order_id: UUID | None = None
    invoice_number: str | None = None
    received_date: date
    items: list[GrnItemCreate] = Field(min_length=1)


class GrnItemOut(BaseModel):
    id: UUID
    item_id: UUID
    batch_number: str | None
    expiry_date: date | None
    quantity: Decimal
    unit_price: Decimal | None


class GrnOut(BaseModel):
    id: UUID
    supplier_id: UUID
    purchase_order_id: UUID | None
    invoice_number: str | None
    received_date: date
    status: str
    items: list[GrnItemOut]


class IndentItemCreate(BaseModel):
    item_id: UUID
    quantity_requested: Decimal


class IndentCreate(BaseModel):
    department_id: UUID
    items: list[IndentItemCreate]


class IndentItemOut(BaseModel):
    id: UUID
    item_id: UUID
    quantity_requested: Decimal


class IndentOut(BaseModel):
    id: UUID
    department_id: UUID
    status: str
    approved_by: UUID | None
    items: list[IndentItemOut]


class IndentApprovalRequest(BaseModel):
    approve: bool
    reason: str | None = None


class ReorderAlertItem(BaseModel):
    item_id: UUID
    item_name: str
    reorder_level: Decimal
    current_stock: Decimal


class ReorderAlertsResponse(BaseModel):
    items: list[ReorderAlertItem]


class AdjustmentCreate(BaseModel):
    item_id: UUID
    batch_id: UUID
    quantity_change: Decimal
    reason: str
    first_approver_id: UUID


class AdjustmentOut(BaseModel):
    id: UUID
    item_id: UUID
    batch_id: UUID
    quantity_change: Decimal
    reason: str
    first_approver_id: UUID
    second_approver_id: UUID | None
    status: str


class AdjustmentApprovalRequest(BaseModel):
    approve: bool
    reason: str | None = None


class GrnVerifyRequest(BaseModel):
    stock_location_id: UUID

class ExpiringBatch(BaseModel):
    batch_id: UUID
    item_id: UUID
    item_name: str
    batch_number: str
    expiry_date: str
    days_to_expiry: int
    quantity: Decimal
    stock_location_id: UUID
    stock_location_name: str


class ExpiryTrackerResponse(BaseModel):
    items: list[ExpiringBatch]
    threshold_days: int


# -- Master data the procurement screens need to exist at all ----------------
#
# suppliers and stock_locations have existed since migration 0012 with no
# endpoint over either. A GRN carries a supplier_id and verification carries a
# stock_location_id, so without these two reads the receiving screen has no
# pickers and the workflow cannot be started from the UI at all.

class SupplierOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    name: str
    contact_info: str | None
    is_active: bool


class SupplierListOut(BaseModel):
    items: list[SupplierOut]


class ApproverCandidateOut(BaseModel):
    """A colleague a pharmacist may nominate as first approver.

    Deliberately narrower than `UserOut`. The adjustment screen needs a name to
    put on a button; it does not need email, mobile, employee id or
    registration number, and the pharmacist who owns that screen has no reason
    to be handed the facility's staff directory to obtain one.
    """

    model_config = {"from_attributes": True}

    id: UUID
    full_name: str
    designation: str | None


class ApproverCandidateListOut(BaseModel):
    items: list[ApproverCandidateOut]


class StockLocationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    name: str
    location_type: str
    department_id: UUID | None


class StockLocationListOut(BaseModel):
    items: list[StockLocationOut]


# -- Procurement read side --------------------------------------------------
#
# GRN, indents and adjustments were WRITE-ONLY: each had a POST to create and a
# POST to approve, and no GET anywhere. Every endpoint works perfectly in
# isolation, which is why it survived review — but an HOD had no way to find an
# indent to approve and a second pharmacist no way to find an adjustment to
# sign. The approval workflow was unreachable without already knowing the UUID.
#
# The list rows carry display names rather than bare ids. A screen showing
# "adjust 40 units of 3f2a…-…" is not reviewable, and a reviewer who cannot
# read what they are signing is not a control.

class GrnListItem(BaseModel):
    id: UUID
    supplier_id: UUID
    purchase_order_id: UUID | None
    supplier_name: str
    invoice_number: str | None
    received_date: date
    status: str
    line_count: int
    created_at: datetime
    #: There is no verified_at column — verification is visible only as
    #: status='verified'. Worth knowing when reading this screen: the GRN does
    #: not record WHEN stock was posted, only that it was. The stock_ledger
    #: rows carry the timestamp, so that is where a reconciliation has to look.
    updated_at: datetime


class GrnListOut(BaseModel):
    items: list[GrnListItem]


class IndentListItem(BaseModel):
    id: UUID
    department_id: UUID
    department_name: str
    status: str
    approved_by: UUID | None
    approved_by_name: str | None
    line_count: int
    created_at: datetime


class IndentListOut(BaseModel):
    items: list[IndentListItem]


class AdjustmentListItem(BaseModel):
    id: UUID
    item_id: UUID
    item_name: str
    batch_id: UUID
    batch_number: str
    expiry_date: date
    #: Signed. Negative is a write-down, which is the direction that conceals loss.
    quantity_change: Decimal
    #: What the batch holds now, so a reviewer can see whether the result is sane.
    quantity_on_hand: Decimal
    reason: str
    status: str
    created_by: UUID
    created_by_name: str
    first_approver_id: UUID
    first_approver_name: str
    second_approver_id: UUID | None
    second_approver_name: str | None
    created_at: datetime


class AdjustmentListOut(BaseModel):
    items: list[AdjustmentListItem]

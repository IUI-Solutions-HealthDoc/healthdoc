"""
Pydantic schemas for the invoice-builder slice of the billing module
(B7-W2-01 — issue #168), plus the payment/refund slice (B7-W3-01 —
issue #188).

These sit alongside whatever CRUD schemas already exist in
app/billing/schemas.py for Invoice / InvoiceItem / Payment / Refund
(InvoiceCreate, InvoiceOut, etc.). Only the schemas needed for these
tickets — preview, build, PM-JAY eligibility stub, payments, refunds —
are defined here; merge into the existing schemas.py rather than
replacing it.

Field names intentionally mirror the DB columns (snake_case) per the
API contract in the schema doc (§4.2: "JSON keys = DB column names").
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.common.enums import ChargeCategory, PaymentMode, PaymentStatus  # single source of truth — don't re-list values here


# ---------------------------------------------------------------------
# Charge lines — a "chargeable unit of work" discovered somewhere in the
# clinical tables (lab_order_items, radiology_order_items,
# pharmacy_dispense_items, ...) that does not yet have a matching
# invoice_items row.
# ---------------------------------------------------------------------

class ChargeLine(BaseModel):
    """One prospective invoice_items row, before it's written."""

    charge_category: ChargeCategory
    reference_type: str = Field(..., description="Source table, e.g. 'lab_order_items'")
    reference_id: uuid.UUID
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal
    amount: Decimal
    priced: bool = Field(
        True,
        description=(
            "False if no price could be resolved for this line (pricing "
            "catalog stub returned nothing) — such lines are reported but "
            "never written to invoice_items with a null/zero price."
        ),
    )
    pricing_note: str | None = Field(
        None, description="Set when priced=False, explains why."
    )


class InvoicePreviewResponse(BaseModel):
    """Response for GET /billing/invoices/{visit_id}/preview — read-only, no DB writes."""

    visit_id: uuid.UUID
    patient_id: uuid.UUID | None = Field(
        None,
        description=(
            "Resolved even when invoice_id is null (looked up via the visit), "
            "since consuming code (the data_access_log decorator, B7-W2-02) "
            "needs a patient_id to log against regardless of invoice state."
        ),
    )
    invoice_id: uuid.UUID | None = Field(
        None, description="Null if no invoice exists yet for this visit."
    )
    invoice_status: str | None = None
    already_billed_count: int = Field(
        ..., description="Existing invoice_items rows already on the invoice."
    )
    new_charge_lines: list[ChargeLine]
    unpriced_count: int = Field(
        ..., description="Subset of new_charge_lines with priced=False."
    )
    projected_new_charges_total: Decimal
    projected_gross_amount: Decimal = Field(
        ..., description="Existing invoice gross_amount + projected_new_charges_total."
    )


class InvoiceBuildRequest(BaseModel):
    """Body for POST /billing/invoices/{visit_id}/build."""

    dry_run: bool = Field(
        False,
        description="If true, behaves exactly like /preview and writes nothing.",
    )


class InvoiceBuildResponse(BaseModel):
    visit_id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_number: str
    status: str
    lines_added: int
    lines_skipped_unpriced: int
    gross_amount: Decimal
    net_amount: Decimal


# ---------------------------------------------------------------------
# PM-JAY eligibility — STUB. Real ABDM/PM-JAY beneficiary verification
# is a certification-track integration owned by seniors (per project
# scope notes); this only wires the shape of the response and a
# config-driven (never hardcoded) lookup so the real check can be
# dropped in later without changing the API contract.
# ---------------------------------------------------------------------

PMJAYEligibilityStatus = Literal["eligible", "not_eligible", "not_determined"]


class PMJAYEligibilityResponse(BaseModel):
    patient_id: uuid.UUID
    visit_id: uuid.UUID
    scheme_code: Literal["PM-JAY"] = "PM-JAY"
    eligibility_status: PMJAYEligibilityStatus
    reason: str
    is_stub: bool = Field(
        True,
        description=(
            "Always true until real ABDM/PM-JAY beneficiary verification "
            "is integrated. Callers must not treat 'eligible' from this "
            "endpoint as a billing guarantee — it only gates whether the "
            "front desk is prompted to collect scheme documents."
        ),
    )


# ---------------------------------------------------------------------
# Payments — B7-W3-01 (#188).
#
# Payment receipts are immutable after save (schema doc §22.3 / §35.4.4;
# see migrations/00xx_payment_refund_immutability.py). There is
# deliberately no PaymentUpdate / PATCH schema anywhere in this module —
# corrections are always a new Refund row, never an edit. See
# service.record_payment for the balance/overpayment checks and the
# invoice status transition (issued -> partially_paid -> paid).
# ---------------------------------------------------------------------

class PaymentCreate(BaseModel):
    """Body for POST /billing/invoices/{invoice_id}/payments."""

    amount: Decimal = Field(..., gt=0, description="Must not exceed the invoice's remaining balance.")
    mode: PaymentMode
    currency: str = Field("INR", min_length=3, max_length=3)
    collected_at: str | None = Field(
        None,
        description=(
            "ISO-8601 UTC timestamp of when cash/UPI/card was actually "
            "collected, if different from 'now' (e.g. backdating a "
            "receptionist's end-of-shift batch entry). Defaults to now() "
            "if omitted."
        ),
    )


class PaymentOut(BaseModel):
    """Response shape per schema doc §4.4 — /billing/invoices/{id}/payments."""

    id: uuid.UUID
    receipt_number: str
    invoice_id: uuid.UUID
    amount: Decimal
    currency: str
    mode: PaymentMode
    status: PaymentStatus
    collected_at: str


# ---------------------------------------------------------------------
# Refunds — B7-W3-01 (#188). Reversal ledger, not an edit path.
#
# Gated by the "billing_refunds" toggleable module (schema doc §3 0027 /
# ModuleCode.BILLING_REFUNDS) — unlike invoices/payments, which are core
# billing and can never be disabled. See router.py.
# ---------------------------------------------------------------------

class RefundCreate(BaseModel):
    """Body for POST /billing/payments/{payment_id}/refunds."""

    amount: Decimal = Field(..., gt=0, description="Must not exceed the payment's un-refunded balance.")
    reason: str = Field(..., min_length=1)


class RefundOut(BaseModel):
    """Response shape per schema doc §4.4 — /billing/payments/{id}/refunds."""

    id: uuid.UUID
    refund_number: str
    payment_id: uuid.UUID
    amount: Decimal
    reason: str
    approved_by: uuid.UUID
    refunded_at: str

"""
Pydantic schemas for billing: invoice builder (#168), payments/refunds (#188),
billing MIS (#189). Merge into existing schemas.py, don't replace it.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.common.enums import ChargeCategory, PaymentMode, PaymentStatus


class ChargeLine(BaseModel):
    """One prospective invoice_items row, before it's written."""

    charge_category: ChargeCategory
    reference_type: str = Field(..., description="Source table, e.g. 'lab_order_items'")
    reference_id: uuid.UUID
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal
    amount: Decimal
    priced: bool = Field(True, description="False if no tariff was found — never written to invoice_items.")
    pricing_note: str | None = Field(None, description="Set when priced=False.")


class InvoicePreviewResponse(BaseModel):
    """GET /billing/invoices/{visit_id}/preview — read-only."""

    visit_id: uuid.UUID
    patient_id: uuid.UUID | None = Field(None, description="Resolved via visit even if no invoice exists yet.")
    invoice_id: uuid.UUID | None = Field(None, description="Null if no invoice exists yet.")
    invoice_status: str | None = None
    already_billed_count: int
    new_charge_lines: list[ChargeLine]
    unpriced_count: int
    projected_new_charges_total: Decimal
    projected_gross_amount: Decimal


class InvoiceBuildRequest(BaseModel):
    dry_run: bool = Field(False, description="If true, behaves like /preview — writes nothing.")


class InvoiceBuildResponse(BaseModel):
    visit_id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_number: str
    status: str
    lines_added: int
    lines_skipped_unpriced: int
    gross_amount: Decimal
    net_amount: Decimal


# PM-JAY eligibility — STUB, not a real ABDM check yet.
PMJAYEligibilityStatus = Literal["eligible", "not_eligible", "not_determined"]


class PMJAYEligibilityResponse(BaseModel):
    patient_id: uuid.UUID
    visit_id: uuid.UUID
    scheme_code: Literal["PM-JAY"] = "PM-JAY"
    eligibility_status: PMJAYEligibilityStatus
    reason: str
    is_stub: bool = Field(True, description="Not a billing guarantee — only gates front-desk doc collection.")


# Payments — immutable after save, no PATCH schema. Corrections = new Refund row.

class PaymentCreate(BaseModel):
    """Body for POST /billing/invoices/{invoice_id}/payments."""

    amount: Decimal = Field(..., gt=0, description="Must not exceed the invoice's remaining balance.")
    mode: PaymentMode
    currency: str = Field("INR", min_length=3, max_length=3)
    collected_at: str | None = Field(None, description="ISO-8601 UTC; defaults to now() if omitted.")


class PaymentOut(BaseModel):
    id: uuid.UUID
    receipt_number: str
    invoice_id: uuid.UUID
    amount: Decimal
    currency: str
    mode: PaymentMode
    status: PaymentStatus
    collected_at: str


# Refunds — reversal ledger, gated by the "billing_refunds" toggleable module (see router.py).

class RefundCreate(BaseModel):
    """Body for POST /billing/payments/{payment_id}/refunds."""

    amount: Decimal = Field(..., gt=0, description="Must not exceed the payment's un-refunded balance.")
    reason: str = Field(..., min_length=1)


class RefundOut(BaseModel):
    id: uuid.UUID
    refund_number: str
    payment_id: uuid.UUID
    amount: Decimal
    reason: str
    approved_by: uuid.UUID
    refunded_at: str


# Billing MIS — read-only, computed live (not from kpi_snapshots). Facility-scoped.

class DailyRevenuePoint(BaseModel):
    day: date
    payment_count: int
    gross_collected: Decimal
    refunded: Decimal
    net_revenue: Decimal


class DailyRevenueResponse(BaseModel):
    facility_id: uuid.UUID
    date_from: date
    date_to: date
    points: list[DailyRevenuePoint]
    total_net_revenue: Decimal


class PendingInvoiceLine(BaseModel):
    invoice_id: uuid.UUID
    invoice_number: str
    visit_id: uuid.UUID
    patient_id: uuid.UUID
    status: str
    net_amount: Decimal
    paid_amount: Decimal
    balance_due: Decimal
    created_at: str
    days_pending: int


class PendingInvoicesResponse(BaseModel):
    facility_id: uuid.UUID
    as_of: str
    count: int
    total_balance_due: Decimal
    items: list[PendingInvoiceLine]


class SchemeBreakdownLine(BaseModel):
    scheme_code: str  # "self_pay" when invoices.scheme_code is NULL
    invoice_count: int
    net_billed: Decimal
    scheme_adjustment_total: Decimal
    collected_total: Decimal  # payments minus refunds


class SchemeBreakdownResponse(BaseModel):
    facility_id: uuid.UUID
    date_from: date
    date_to: date
    lines: list[SchemeBreakdownLine]
    grand_total_net_billed: Decimal

"""
Pydantic schemas for billing: invoice builder (#168), payments/refunds (#188),
billing MIS (#189). Merge into existing schemas.py, don't replace it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.common.enums import ChargeCategory, PaymentMode, PaymentStatus

# Money fields serialize as JSON strings, not numbers — schema doc §4.2:
# "amount as string (JSON floats corrupt paise)". quantity is not money —
# stays plain Decimal.
Money = Annotated[Decimal, PlainSerializer(lambda v: str(v), return_type=str, when_used="json")]


class InvoiceListItemOut(BaseModel):
    id: uuid.UUID
    invoice_number: str
    visit_id: uuid.UUID
    patient_id: uuid.UUID
    patient_full_name: str
    patient_identifier: str
    status: str
    gross_amount: Money
    net_amount: Money
    scheme_code: str | None
    row_version: int
    created_at: datetime


class InvoiceListOut(BaseModel):
    items: list[InvoiceListItemOut]
    page: int
    page_size: int
    total: int


class ChargeLine(BaseModel):
    """One prospective invoice_items row, before it's written."""

    charge_category: ChargeCategory
    reference_type: str = Field(..., description="Source table, e.g. 'lab_order_items'")
    reference_id: uuid.UUID
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Money
    amount: Money
    priced: bool = Field(True, description="False if no tariff was found — never written to invoice_items.")
    pricing_note: str | None = Field(None, description="Set when priced=False.")
    charge_master_id: uuid.UUID | None = Field(None, description="Exact tariff version pinned at accrual; null for batch-priced pharmacy.")
    charge_code: str | None = None
    pricing_date: date | None = Field(None, description="Recorded visit's facility-local date used for tariff selection.")


class InvoicePreviewResponse(BaseModel):
    """GET /billing/invoices/{visit_id}/preview — read-only."""

    visit_id: uuid.UUID
    patient_id: uuid.UUID | None = Field(None, description="Resolved via visit even if no invoice exists yet.")
    invoice_id: uuid.UUID | None = Field(None, description="Null if no invoice exists yet.")
    invoice_status: str | None = None
    already_billed_count: int
    new_charge_lines: list[ChargeLine]
    unpriced_count: int
    projected_new_charges_total: Money
    projected_gross_amount: Money


class InvoiceBuildRequest(BaseModel):
    dry_run: bool = Field(False, description="If true, behaves like /preview — writes nothing.")


class InvoiceBuildResponse(BaseModel):
    visit_id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_number: str
    status: str
    lines_added: int
    lines_skipped_unpriced: int
    gross_amount: Money
    net_amount: Money


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

    amount: Money = Field(..., gt=0, description="Must not exceed the invoice's remaining balance.")
    mode: PaymentMode
    currency: str = Field("INR", min_length=3, max_length=3)
    collected_at: str | None = Field(None, description="ISO-8601 UTC; defaults to now() if omitted.")


class PaymentOut(BaseModel):
    id: uuid.UUID
    receipt_number: str
    invoice_id: uuid.UUID
    amount: Money
    currency: str
    mode: PaymentMode
    status: PaymentStatus
    collected_at: str


class RefundOnPaymentOut(BaseModel):
    """A reversal against one receipt.

    Refunds were WRITE-ONLY: POST /billing/payments/{id}/refunds created them and
    no endpoint anywhere read one back. A billing screen that cannot show a
    reversal shows a patient a balance that disagrees with their receipt.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    refund_number: str
    payment_id: uuid.UUID
    amount: Money
    reason: str
    approved_by: uuid.UUID
    refunded_at: datetime


class PaymentWithRefundsOut(PaymentOut):
    """A receipt with its reversals nested, for the invoice detail screen."""

    refunds: list[RefundOnPaymentOut] = []


class InvoiceLineOut(BaseModel):
    """One invoice_items row. No created_by/updated_by: InvoiceItem is
    `(UUIDPk, Base)` — it carries neither the Blame nor the Timestamps mixin,
    and migration 0014 gives it only created_at. Authorship lives on the
    invoice, not the line."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    charge_category: str
    reference_type: str | None
    reference_id: uuid.UUID | None
    charge_master_id: uuid.UUID | None
    description: str
    quantity: Decimal
    unit_price: Money
    amount: Money
    created_at: datetime


class InvoiceDetailOut(BaseModel):
    """One invoice with its charge lines, its receipts, and what is still owed.

    Three frontend mocks stood in for this — getInvoice, listPayments and
    getInvoiceBalance — and none had a backend. They are one endpoint because
    they are one screen: a clerk looking at an invoice needs the lines, what has
    been received against it, and the remaining balance together, and computing
    the balance in the browser from two separate calls invites the two halves to
    disagree mid-payment.

    `balance_due` is net_amount - (successful payments - refunds), computed
    server-side by the same helper record_payment uses to decide whether the
    invoice is now partially_paid or paid. There is deliberately no second
    implementation of that arithmetic.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    invoice_number: str
    visit_id: uuid.UUID
    patient_id: uuid.UUID
    patient_full_name: str
    patient_identifier: str
    facility_id: uuid.UUID
    status: str
    gross_amount: Money
    discount_amount: Money
    scheme_adjustment: Money
    net_amount: Money
    scheme_code: str | None
    row_version: int
    created_at: datetime

    lines: list[InvoiceLineOut]
    payments: list[PaymentWithRefundsOut]
    total_paid: Money
    total_refunded: Money
    balance_due: Money



# Refunds — reversal ledger. Core module per schema doc v3.13 (not toggleable — see router.py).

class RefundCreate(BaseModel):
    """Body for POST /billing/payments/{payment_id}/refunds."""

    amount: Money = Field(..., gt=0, description="Must not exceed the payment's un-refunded balance.")
    reason: str = Field(..., min_length=1)


class RefundOut(BaseModel):
    id: uuid.UUID
    refund_number: str
    payment_id: uuid.UUID
    amount: Money
    reason: str
    approved_by: uuid.UUID
    refunded_at: str


# Billing MIS — read-only, computed live (not from kpi_snapshots). Facility-scoped.
# day / date_from / date_to are facility-local business dates (facilities.timezone),
# not UTC — see service._facility_business_date.

class DailyRevenuePoint(BaseModel):
    day: date
    payment_count: int
    gross_collected: Money
    refunded: Money
    net_revenue: Money


class DailyRevenueResponse(BaseModel):
    facility_id: uuid.UUID
    date_from: date
    date_to: date
    points: list[DailyRevenuePoint]
    total_net_revenue: Money


class PendingInvoiceLine(BaseModel):
    invoice_id: uuid.UUID
    invoice_number: str
    visit_id: uuid.UUID
    patient_id: uuid.UUID
    status: str
    net_amount: Money
    paid_amount: Money
    balance_due: Money
    created_at: str
    days_pending: int


class PendingInvoicesResponse(BaseModel):
    facility_id: uuid.UUID
    as_of: str
    count: int
    total_balance_due: Money
    items: list[PendingInvoiceLine]


class SchemeBreakdownLine(BaseModel):
    scheme_code: str  # "self_pay" when invoices.scheme_code is NULL
    invoice_count: int
    net_billed: Money
    scheme_adjustment_total: Money
    collected_total: Money  # payments minus refunds


class SchemeBreakdownResponse(BaseModel):
    facility_id: uuid.UUID
    date_from: date
    date_to: date
    lines: list[SchemeBreakdownLine]
    grand_total_net_billed: Money


# ============================================================ charge_master admin (#287)

class TariffCreate(BaseModel):
    """A new tariff row. Never an edit of an existing one — see
    billing.service.create_tariff for why a price change must be a new row."""

    charge_code: str = Field(..., max_length=30,
                             description="Stable across price changes, e.g. REGISTRATION, CBC.")
    description: str = Field(..., min_length=1)
    charge_category: str = Field(..., description="registration | consultation | lab | radiology "
                                                  "| pharmacy | procedure | ipd_stay | blood | other")
    unit_price: Decimal = Field(..., ge=0, decimal_places=2)
    effective_from: date = Field(..., description="Must be after the current row's effective_from; "
                                                  "back-dating would change what past invoices resolve to.")
    scheme_code: str | None = Field(
        default=None, max_length=30,
        description="NULL is the general tariff. A scheme rate (PMJAY etc.) wins over it "
                    "when the invoice carries that scheme_code.",
    )

    @field_validator("charge_category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        if v not in ChargeCategory.values():
            raise ValueError(f"charge_category must be one of: {sorted(ChargeCategory.values())}")
        return v


class TariffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    facility_id: UUID
    charge_code: str
    description: str
    charge_category: str
    unit_price: Decimal
    scheme_code: str | None
    effective_from: date
    effective_to: date | None
    is_active: bool

"""
SQLAlchemy models for the billing module.

invoices has a real DB trigger (trg_invoices_freeze) that blocks editing
frozen columns once the invoice leaves 'draft' status. invoice_items has
its own second trigger that blocks edits/deletes once the PARENT invoice
leaves 'draft'. Both triggers live in the migration file, not here — raw
SQL, same reasoning as audit_logs' triggers (Alembic autogenerate can't
produce trigger DDL).

visit_id / patient_id / facility_id all get REAL ForeignKey()s here,
unlike audit_logs/consent_records in earlier migrations — visits (0007),
patients (0006), and facilities (0002) already exist earlier in the
migration chain by number, so there's no need to defer these FKs.

Status/mode/category columns (status, mode, charge_category, counter_type)
use plain string values with literal CHECK constraints instead of
CheckedEnum classes from app/common/enums.py — that file is outside this
task's scope, so no new enum classes were added here. If/when
InvoiceStatus, PaymentMode, PaymentStatus, ChargeCategory get added to
enums.py by whoever owns that file, these CHECK constraints can be
swapped to EnumClass.sql_check() in a follow-up.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Blame, Timestamps, UUIDPk


class Invoice(UUIDPk, Blame, Timestamps, Base):
    """
    One invoice per visit. Starts as 'draft'; departments append charge
    lines as chargeable work completes. Once status leaves 'draft'
    (issued/partially_paid/paid/waived/cancelled), a DB trigger
    (trg_invoices_freeze) blocks changes to everything except
    status/updated_at/updated_by — so a payment can still move the
    invoice through issued -> partially_paid -> paid, but nobody can
    quietly edit the amounts after the fact. Corrections are always
    "cancel + create a new invoice", never an edit.
    """

    __tablename__ = "invoices"

    invoice_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)

    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("visits.id", ondelete="RESTRICT", name="fk_invoices_visit_id"),
        nullable=False,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="RESTRICT", name="fk_invoices_patient_id"),
        nullable=False,
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="RESTRICT", name="fk_invoices_facility_id"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="draft")  # draft|issued|partially_paid|paid|waived|cancelled
    gross_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    discount_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    scheme_adjustment: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    net_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    scheme_code: Mapped[str | None] = mapped_column(String(30), nullable=True)  # e.g. PM-JAY
    sensitivity: Mapped[str] = mapped_column(String(30), nullable=False, server_default="critical")

    __table_args__ = (
        Index("ix_invoices_visit_id", "visit_id"),
        Index("ix_invoices_patient_id", "patient_id"),
        Index("ix_invoices_facility_id", "facility_id"),
        CheckConstraint(
            "status IN ('draft', 'issued', 'partially_paid', 'paid', 'waived', 'cancelled')",
            name="ck_invoices_status",
        ),
        CheckConstraint("net_amount >= 0", name="ck_invoices_net_amount_non_negative"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Invoice id={self.id} number={self.invoice_number} status={self.status}>"


class InvoiceItem(UUIDPk, Base):
    """
    One charge line on an invoice (e.g. one lab test's fee). Frozen by a
    SECOND trigger (trg_invoice_items_freeze) that looks up the parent
    invoice's status — once that parent leaves 'draft', this row can no
    longer be edited or deleted. No Timestamps mixin: this row is either
    still-editable (while parent is draft) or fully frozen — there's no
    in-between state that needs an updated_at.
    """

    __tablename__ = "invoice_items"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="RESTRICT", name="fk_invoice_items_invoice_id"),
        nullable=False,
    )
    charge_category: Mapped[str] = mapped_column(String(50), nullable=False)  # registration|consultation|lab|radiology|pharmacy|procedure|ipd_stay|blood|other
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g. 'lab_order_items'
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, server_default="1")
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)  # quantity * unit_price, app-computed
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_invoice_items_invoice_id", "invoice_id"),
        CheckConstraint(
            "charge_category IN ('registration','consultation','lab','radiology','pharmacy',"
            "'procedure','ipd_stay','blood','other')",
            name="ck_invoice_items_charge_category",
        ),
        CheckConstraint("quantity > 0", name="ck_invoice_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_invoice_items_unit_price_non_negative"),
        CheckConstraint("amount >= 0", name="ck_invoice_items_amount_non_negative"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InvoiceItem id={self.id} invoice={self.invoice_id} amount={self.amount}>"


class Payment(UUIDPk, Blame, Timestamps, Base):
    """Partial payments are allowed — many payment rows can point at one invoice."""

    __tablename__ = "payments"

    receipt_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="RESTRICT", name="fk_payments_invoice_id"),
        nullable=False,
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    mode: Mapped[str] = mapped_column(String(50), nullable=False)  # cash|upi|card|netbanking
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="success")  # success|reversed
    collected_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_payments_collected_by"),
        nullable=False,
    )
    collected_at: Mapped[datetime] = mapped_column(nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(30), nullable=False, server_default="critical")

    __table_args__ = (
        Index("ix_payments_invoice_id", "invoice_id"),
        Index("ix_payments_collected_by", "collected_by"),
        CheckConstraint("mode IN ('cash','upi','card','netbanking')", name="ck_payments_mode"),
        CheckConstraint("status IN ('success','reversed')", name="ck_payments_status"),
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Payment id={self.id} receipt={self.receipt_number} amount={self.amount}>"


class Refund(UUIDPk, Blame, Timestamps, Base):
    """A refund is always a NEW reversal row — it never edits the original payment."""

    __tablename__ = "refunds"

    refund_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="RESTRICT", name="fk_refunds_payment_id"),
        nullable=False,
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_refunds_approved_by"),
        nullable=False,
    )
    refunded_at: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        Index("ix_refunds_payment_id", "payment_id"),
        Index("ix_refunds_approved_by", "approved_by"),
        CheckConstraint("amount > 0", name="ck_refunds_amount_positive"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Refund id={self.id} number={self.refund_number} amount={self.amount}>"


class BillingCounter(UUIDPk, Timestamps, Base):
    """
    Gapless number allocator for invoice/receipt/refund numbers. The app
    reads + increments last_value inside a `SELECT ... FOR UPDATE`
    transaction so numbers never skip — a plain Postgres SEQUENCE would
    leave gaps on rollback, which billing numbering can't have.
    """

    __tablename__ = "billing_counters"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="RESTRICT", name="fk_billing_counters_facility_id"),
        nullable=False,
    )
    counter_type: Mapped[str] = mapped_column(String(50), nullable=False)  # invoice | receipt | refund
    counter_date: Mapped[date] = mapped_column(nullable=False)
    last_value: Mapped[int] = mapped_column(nullable=False, server_default="0")

    __table_args__ = (
        Index("ix_billing_counters_facility_id", "facility_id"),
        UniqueConstraint(
            "facility_id", "counter_type", "counter_date",
            name="uq_billing_counters_facility_type_date",
        ),
        CheckConstraint("counter_type IN ('invoice','receipt','refund')", name="ck_billing_counters_counter_type"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BillingCounter facility={self.facility_id} type={self.counter_type} date={self.counter_date}>"

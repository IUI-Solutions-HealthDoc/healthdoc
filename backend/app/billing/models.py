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
now use ChargeCategory / PaymentMode / PaymentStatus from
app/common/enums.py for their CHECK constraints via .sql_check() —
per code review, these enum classes exist (ADR 0002) and schemas.py
already imports them, so the migration's literal value lists were
drift-prone. InvoiceStatus exists in enums.py too but invoices.status
keeps a plain literal list here on purpose: InvoiceStatus doesn't
include every transitional detail this table's trigger cares about
beyond the 6 values already listed, so this is a 1:1 swap only where
the enum and the column are the same closed set.

PR review fixes applied (2 days ago, solutionsiui):
  - Blocker 3: money columns were Mapped[float] over Numeric(12,2) —
    SQLAlchemy returns Decimal at runtime regardless, so this wasn't
    corrupting data, but it lied to every type checker/reader that
    float arithmetic was fine here. Now Mapped[Decimal].
  - Blocker 4: collected_at / refunded_at had no explicit column type,
    so SQLAlchemy inferred a naive DateTime while the migration creates
    TIMESTAMP(timezone=True) — DB stores aware, ORM handed back naive,
    every comparison silently off by the facility offset. Now
    DateTime(timezone=True) explicitly, same as InvoiceItem.created_at.
  - Should-fix: sensitivity/scheme_code widened varchar(30) -> 50
    (repo blanket rule for enum/status-ish columns).
  - Should-fix: row_version added to invoices for optimistic
    concurrency (§4A) — two clerks editing a draft invoice no longer
    silently last-write-wins; service.py bumps it on every mutation
    and callers can send If-Match / expected_row_version to detect a
    stale write (wiring that check into the endpoints is a follow-up,
    tracked alongside the row itself so the column exists now rather
    than needing a second migration later).
  - Should-fix (mixin order) reviewed but NOT applied: the review
    suggested (Base, UUIDPk, Timestamps, Blame) to match "the rest of
    the repo", but app/audit/models.py — the one other module actually
    in this codebase right now — uses (UUIDPk, Timestamps, Base) /
    (UUIDPk, Base), i.e. Base LAST, same as billing already had. Kept
    the existing (UUIDPk, Blame, Timestamps, Base) order rather than
    diverge from the one real precedent available; flagging the
    discrepancy back to the reviewer instead of guessing.

Audit (app/audit/listeners.py, issue #290, B7 rollout item):
  Only Invoice opts into automatic audit trail below
  (__audit_resource_type__ etc.) — it's the only table in this module
  with a real facility_id column, which the listener requires. Every
  Invoice UPDATE (status/gross_amount/net_amount changes from
  build_invoice/record_payment/create_refund) is now audited for free.
  InvoiceItem/Payment/Refund/BillingCounter do NOT have a facility_id
  column (schema doc doesn't put one there — they're reached via
  invoice_id/payment_id), so they structurally cannot opt into the
  same mechanism without a schema change, which is out of scope here.
  Their creation is audited manually instead, via
  app.audit.service.write_audit_log() called from service.py at the
  point where each row is created (invoice.facility_id is already
  in scope there). Because of this split, app.billing is NOT added to
  listeners.AUDITABLE_MODULE_PREFIXES yet — that switch asserts EVERY
  model in the module opted in, which isn't true here and won't be
  until either these tables gain a facility_id column or listeners.py
  grows a way to resolve it via a relationship. Flagged for Tech Lead
  under #290, not silently worked around.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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
from app.common.enums import ChargeCategory, PaymentMode, PaymentStatus
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

    # --- audit opt-in (app/audit/listeners.py) — see module docstring ---
    __audit_resource_type__ = "invoices"
    __audit_facility_id_field__ = "facility_id"
    __audit_patient_id_field__ = "patient_id"
    __audit_visit_id_field__ = "visit_id"

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
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    scheme_adjustment: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    net_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    scheme_code: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g. PM-JAY
    sensitivity: Mapped[str] = mapped_column(String(50), nullable=False, server_default="critical")

    # Optimistic concurrency (§4A) — bumped by service.py on every write
    # to this row. Two clerks loading the same draft invoice and both
    # saving no longer silently last-write-wins; a client can send back
    # the row_version it read and get a 409 if it's stale.
    row_version: Mapped[int] = mapped_column(nullable=False, server_default="1")

    __table_args__ = (
        Index("ix_invoices_visit_id", "visit_id"),
        Index("ix_invoices_patient_id", "patient_id"),
        Index("ix_invoices_facility_id", "facility_id"),
        CheckConstraint(
            "status IN ('draft', 'issued', 'partially_paid', 'paid', 'waived', 'cancelled')",
            name="status",
        ),
        CheckConstraint("net_amount >= 0", name="net_amount_non_negative"),
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

    No facility_id column (reached only via invoice_id) — cannot opt
    into app/audit/listeners.py's automatic hook (see module docstring
    on Invoice). Creation is audited manually from service.build_invoice().

    A partial UNIQUE index on (invoice_id, reference_type, reference_id)
    — uq_invoice_items_source, WHERE both columns are non-null — lands
    in migration 0033 (#285, owned by solutionsiui) alongside
    charge_master. That is the real fix for the double-billing race
    (blocker #2 in review): app-level dedupe in
    service._already_billed_reference_ids() is a fast path only, never
    the source of truth, until this repo rebases onto 0033. See
    service.py's insert loop for how a conflict is now handled as a
    no-op instead of a 500 in the meantime.
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
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, server_default="1")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)  # quantity * unit_price, app-computed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_invoice_items_invoice_id", "invoice_id"),
        CheckConstraint(ChargeCategory.sql_check("charge_category"), name="charge_category"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InvoiceItem id={self.id} invoice={self.invoice_id} amount={self.amount}>"


class Payment(UUIDPk, Blame, Timestamps, Base):
    """Partial payments are allowed — many payment rows can point at one invoice.

    No facility_id column (reached only via invoice_id) — see Invoice's
    module docstring on why this can't opt into automatic audit.
    Creation is audited manually from service.record_payment().
    Rows are immutable after insert (trg_payments_block, unconditional —
    see migration 0014 item 8); this module never issues UPDATE/DELETE
    against this table.
    """

    __tablename__ = "payments"

    receipt_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="RESTRICT", name="fk_payments_invoice_id"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    mode: Mapped[str] = mapped_column(String(50), nullable=False)  # cash|upi|card|netbanking
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="success")  # success|reversed
    collected_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_payments_collected_by"),
        nullable=False,
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(50), nullable=False, server_default="critical")

    __table_args__ = (
        Index("ix_payments_invoice_id", "invoice_id"),
        Index("ix_payments_collected_by", "collected_by"),
        CheckConstraint(PaymentMode.sql_check("mode"), name="mode"),
        CheckConstraint(PaymentStatus.sql_check("status"), name="status"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Payment id={self.id} receipt={self.receipt_number} amount={self.amount}>"


class Refund(UUIDPk, Blame, Timestamps, Base):
    """A refund is always a NEW reversal row — it never edits the original payment.

    No facility_id column (reached only via payment_id -> invoice_id) —
    see Invoice's module docstring on why this can't opt into automatic
    audit. Creation is audited manually from service.create_refund().
    Rows are immutable after insert (trg_refunds_block, unconditional).
    """

    __tablename__ = "refunds"

    refund_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="RESTRICT", name="fk_refunds_payment_id"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_refunds_approved_by"),
        nullable=False,
    )
    refunded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_refunds_payment_id", "payment_id"),
        Index("ix_refunds_approved_by", "approved_by"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Refund id={self.id} number={self.refund_number} amount={self.amount}>"


class BillingCounter(UUIDPk, Timestamps, Base):
    """
    Gapless number allocator for invoice/receipt/refund numbers. The app
    reads + increments last_value inside a `SELECT ... FOR UPDATE`-
    equivalent upsert transaction so numbers never skip — a plain
    Postgres SEQUENCE would leave gaps on rollback, which billing
    numbering can't have. Same pattern as app.audit.models.AuditCounter.

    Not audited (no facility-scoped business meaning beyond "a counter
    ticked" — same reasoning app/audit applies to its own AuditCounter).
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
        CheckConstraint("counter_type IN ('invoice','receipt','refund')", name="counter_type"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BillingCounter facility={self.facility_id} type={self.counter_type} date={self.counter_date}>"

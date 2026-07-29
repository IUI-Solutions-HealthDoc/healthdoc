"""
Invoice builder service (B7-W2-01 — issue #168) + payment/refund
service (B7-W3-01 — issue #188).

REVISED after seeing app/common/: this stack is fully async
(AsyncSession / asyncpg via db.py), so every DB-touching function here
is async and every db.execute(...) is awaited.

app/common/db.get_db() already commits once, automatically, after the
route handler returns — so this module never calls db.commit() itself.
It calls db.flush() before building the response so that
trg_invoices_freeze / trg_invoice_items_freeze errors (if the guard
below somehow missed a race) surface as a real exception now, not as a
silent no-op discovered later, and db.refresh() to read back
server-computed values within the same still-open transaction. The
same reasoning applies to the new trg_payments_block_update/_delete and
trg_refunds_block_update/_delete triggers (see the B7-W3-01 migration)
— this module never issues an UPDATE/DELETE against payments/refunds
in the first place, so those triggers should never actually fire from
this code; they're a backstop, not something this module routes around.

Status/category values come from app/common/enums.py (ResultStatus,
DispenseStatus, ChargeCategory, PaymentMode, PaymentStatus) instead of
inline strings, per that file's own "never inline strings" rule.

AUDIT LOGGING — intentionally NOT wired in this file. app/audit isn't
implemented yet and nothing on the team has merged anything for it, so
there's no real function, confirmed signature, or confirmed table
shape to call into. Left as TODO comments at the call sites in
build_invoice() / record_payment() / create_refund() — pick it up once
app/audit exists and its owner confirms the interface. Payment/refund
is explicitly listed as an audit event in docs/architecture.html §26.1,
so this matters, but it's not this ticket's job to stub someone else's
module.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Invoice, InvoiceItem, Payment, Refund
from app.billing.pricing import (
    price_lab_test,
    price_pharmacy_batch,
    price_radiology_modality,
)
from app.billing.schemas import (
    ChargeLine,
    InvoiceBuildResponse,
    InvoicePreviewResponse,
    PaymentCreate,
    PaymentOut,
    PMJAYEligibilityResponse,
    RefundCreate,
    RefundOut,
)
from app.common.enums import ChargeCategory, DispenseStatus, PaymentStatus, ResultStatus

TWO_PLACES = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------
# Minimal read-only projections of cross-module tables. Deliberately
# not importing other modules' ORM models — avoids a hard import
# dependency between app/billing and app/{lab,radiology,pharmacy}.
# Swap for real model imports if/when those modules export them for
# cross-module use.
# ---------------------------------------------------------------------

encounters_t = sa.table("encounters", sa.column("id"), sa.column("visit_id"))
orders_t = sa.table("orders", sa.column("id"), sa.column("encounter_id"))

lab_order_items_t = sa.table(
    "lab_order_items",
    sa.column("id"), sa.column("order_id"),
    sa.column("test_code"), sa.column("test_name"),
)
lab_results_t = sa.table(
    "lab_results",
    sa.column("lab_order_item_id"), sa.column("is_current"), sa.column("status"),
)

radiology_order_items_t = sa.table(
    "radiology_order_items",
    sa.column("id"), sa.column("order_id"),
    sa.column("modality"), sa.column("scan_type"),
)
radiology_reports_t = sa.table(
    "radiology_reports",
    sa.column("radiology_order_item_id"), sa.column("is_current"), sa.column("status"),
)

pharmacy_dispenses_t = sa.table(
    "pharmacy_dispenses",
    sa.column("id"), sa.column("visit_id"), sa.column("status"), sa.column("is_current"),
)
pharmacy_dispense_items_t = sa.table(
    "pharmacy_dispense_items",
    sa.column("id"), sa.column("dispense_id"), sa.column("batch_id"),
    sa.column("prescription_item_id"), sa.column("quantity_dispensed"),
)
prescription_items_t = sa.table(
    "prescription_items", sa.column("id"), sa.column("medicine_name"),
)
inventory_batches_t = sa.table(
    "inventory_batches", sa.column("id"), sa.column("issue_rate_mrp"),
)
users_t = sa.table("users", sa.column("id"), sa.column("keycloak_sub"))

# facilities.code (varchar(20), e.g. "JPR001") — schema doc §3 0002.
# Needed to format receipt_number / refund_number
# (RCP-<FACILITY>-<YYYYMMDD>-<SEQ5> / RFD-...). Same cross-module
# read-only-projection approach as the tables above.
facilities_t = sa.table("facilities", sa.column("id"), sa.column("code"))

# billing_counters — gapless allocator (schema doc §3 0014). Real model
# is app.billing.models.BillingCounter; using a bare table projection
# here too since the allocation query below is an INSERT..ON CONFLICT
# upsert, not something the ORM layer buys us anything for.
billing_counters_t = sa.table(
    "billing_counters",
    sa.column("facility_id"), sa.column("counter_type"),
    sa.column("counter_date"), sa.column("last_value"),
)

# A corrected result still means the work is complete/billable — the
# correction itself doesn't un-bill the earlier line (that's a
# refund/dispute concern, out of scope here).
_LAB_BILLABLE_STATUSES = (ResultStatus.FINAL.value, ResultStatus.CORRECTED.value)
_RADIOLOGY_BILLABLE_STATUSES = (ResultStatus.FINAL.value, ResultStatus.CORRECTED.value)
_PHARMACY_BILLABLE_STATUSES = (DispenseStatus.DISPENSED.value, DispenseStatus.PARTIALLY_DISPENSED.value)

# Invoice statuses a payment can be recorded against. 'draft' is
# excluded (nothing to collect against yet — draft invoices are still
# accruing lines); 'paid'/'waived'/'cancelled' are excluded because
# there's no remaining balance / nothing to pay by definition.
_PAYABLE_INVOICE_STATUSES = ("issued", "partially_paid")


async def resolve_actor_user_id(db: AsyncSession, *, keycloak_sub: str, fallback_id: uuid.UUID | None) -> uuid.UUID:
    """
    Blame.created_by/updated_by and audit_logs.user_id are FKs to
    users.id — the app-side UUID, NOT the Keycloak subject. I don't
    have app/auth/deps.py to confirm whether CurrentUser already
    carries the resolved users.id (fallback_id here) or only .sub.
    If it already carries .id, pass it as fallback_id and this
    short-circuits with zero extra queries. If not, this resolves it
    via keycloak_sub. Router calls this so service functions can stay
    agnostic to CurrentUser's exact shape.

    UPDATE (B7-W3-01): app/auth/deps.py is now available — AuthUser only
    has sub/username/roles, no .id field. fallback_id will therefore
    always be None as things stand today, so this always takes the
    keycloak_sub lookup path below. Not a bug — just means the
    zero-extra-queries branch is currently dead code, kept here in case
    CurrentUser grows an .id field later (at which point router.py's
    getattr(user, "id", None) starts returning something and this
    short-circuits for free, no service-layer change needed).
    """
    if fallback_id is not None:
        return fallback_id
    result = await db.execute(sa.select(users_t.c.id).where(users_t.c.keycloak_sub == keycloak_sub))
    user_id = result.scalar_one_or_none()
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No users row matches this token's subject.",
        )
    return user_id


async def _already_billed_reference_ids(
    db: AsyncSession, invoice_id: uuid.UUID, reference_type: str
) -> set[uuid.UUID]:
    result = await db.execute(
        sa.select(InvoiceItem.reference_id).where(
            InvoiceItem.invoice_id == invoice_id,
            InvoiceItem.reference_type == reference_type,
        )
    )
    return set(result.scalars().all())


async def _aggregate_lab_charges(db: AsyncSession, visit_id: uuid.UUID, invoice_id: uuid.UUID) -> list[ChargeLine]:
    billed = await _already_billed_reference_ids(db, invoice_id, "lab_order_items")

    stmt = (
        sa.select(lab_order_items_t.c.id, lab_order_items_t.c.test_code, lab_order_items_t.c.test_name)
        .select_from(
            lab_order_items_t
            .join(orders_t, orders_t.c.id == lab_order_items_t.c.order_id)
            .join(encounters_t, encounters_t.c.id == orders_t.c.encounter_id)
        )
        .where(
            encounters_t.c.visit_id == visit_id,
            sa.exists(
                sa.select(1).where(
                    lab_results_t.c.lab_order_item_id == lab_order_items_t.c.id,
                    lab_results_t.c.is_current.is_(True),
                    lab_results_t.c.status.in_(_LAB_BILLABLE_STATUSES),
                )
            ),
        )
    )

    result = await db.execute(stmt)
    lines: list[ChargeLine] = []
    for row in result:
        if row.id in billed:
            continue
        price = price_lab_test(row.test_code)
        unit_price = price.unit_price if price.unit_price is not None else Decimal("0")
        lines.append(
            ChargeLine(
                charge_category=ChargeCategory.LAB,
                reference_type="lab_order_items",
                reference_id=row.id,
                description=row.test_name,
                quantity=Decimal("1"),
                unit_price=_money(unit_price),
                amount=_money(unit_price),
                priced=price.unit_price is not None,
                pricing_note=price.note,
            )
        )
    return lines


async def _aggregate_radiology_charges(db: AsyncSession, visit_id: uuid.UUID, invoice_id: uuid.UUID) -> list[ChargeLine]:
    billed = await _already_billed_reference_ids(db, invoice_id, "radiology_order_items")

    stmt = (
        sa.select(
            radiology_order_items_t.c.id,
            radiology_order_items_t.c.modality,
            radiology_order_items_t.c.scan_type,
        )
        .select_from(
            radiology_order_items_t
            .join(orders_t, orders_t.c.id == radiology_order_items_t.c.order_id)
            .join(encounters_t, encounters_t.c.id == orders_t.c.encounter_id)
        )
        .where(
            encounters_t.c.visit_id == visit_id,
            sa.exists(
                sa.select(1).where(
                    radiology_reports_t.c.radiology_order_item_id == radiology_order_items_t.c.id,
                    radiology_reports_t.c.is_current.is_(True),
                    radiology_reports_t.c.status.in_(_RADIOLOGY_BILLABLE_STATUSES),
                )
            ),
        )
    )

    result = await db.execute(stmt)
    lines: list[ChargeLine] = []
    for row in result:
        if row.id in billed:
            continue
        price = price_radiology_modality(row.modality)
        unit_price = price.unit_price if price.unit_price is not None else Decimal("0")
        lines.append(
            ChargeLine(
                charge_category=ChargeCategory.RADIOLOGY,
                reference_type="radiology_order_items",
                reference_id=row.id,
                description=row.scan_type,
                quantity=Decimal("1"),
                unit_price=_money(unit_price),
                amount=_money(unit_price),
                priced=price.unit_price is not None,
                pricing_note=price.note,
            )
        )
    return lines


async def _aggregate_pharmacy_charges(db: AsyncSession, visit_id: uuid.UUID, invoice_id: uuid.UUID) -> list[ChargeLine]:
    billed = await _already_billed_reference_ids(db, invoice_id, "pharmacy_dispense_items")

    stmt = (
        sa.select(
            pharmacy_dispense_items_t.c.id,
            pharmacy_dispense_items_t.c.quantity_dispensed,
            prescription_items_t.c.medicine_name,
            inventory_batches_t.c.issue_rate_mrp,
        )
        .select_from(
            pharmacy_dispense_items_t
            .join(pharmacy_dispenses_t, pharmacy_dispenses_t.c.id == pharmacy_dispense_items_t.c.dispense_id)
            .join(prescription_items_t, prescription_items_t.c.id == pharmacy_dispense_items_t.c.prescription_item_id)
            .join(inventory_batches_t, inventory_batches_t.c.id == pharmacy_dispense_items_t.c.batch_id)
        )
        .where(
            pharmacy_dispenses_t.c.visit_id == visit_id,
            pharmacy_dispenses_t.c.is_current.is_(True),
            pharmacy_dispenses_t.c.status.in_(_PHARMACY_BILLABLE_STATUSES),
            pharmacy_dispense_items_t.c.quantity_dispensed > 0,
        )
    )

    result = await db.execute(stmt)
    lines: list[ChargeLine] = []
    for row in result:
        if row.id in billed:
            continue
        price = price_pharmacy_batch(row.issue_rate_mrp)
        qty = Decimal(row.quantity_dispensed)
        unit_price = price.unit_price if price.unit_price is not None else Decimal("0")
        lines.append(
            ChargeLine(
                charge_category=ChargeCategory.PHARMACY,
                reference_type="pharmacy_dispense_items",
                reference_id=row.id,
                description=row.medicine_name,
                quantity=qty,
                unit_price=_money(unit_price),
                amount=_money(unit_price * qty),
                priced=price.unit_price is not None,
                pricing_note=price.note,
            )
        )
    return lines


async def aggregate_unbilled_charges(db: AsyncSession, visit_id: uuid.UUID, invoice_id: uuid.UUID) -> list[ChargeLine]:
    # ipd_stay / procedure / blood deliberately not aggregated — no
    # rate basis (bed-class tariff, OT package price, blood unit
    # price) exists anywhere in the schema yet. Left out rather than
    # guessed; flagged again here since this is the one function that
    # decides "everything chargeable for this visit."
    lab = await _aggregate_lab_charges(db, visit_id, invoice_id)
    radiology = await _aggregate_radiology_charges(db, visit_id, invoice_id)
    pharmacy = await _aggregate_pharmacy_charges(db, visit_id, invoice_id)
    return lab + radiology + pharmacy


async def _get_invoice_for_visit(db: AsyncSession, visit_id: uuid.UUID) -> Invoice:
    result = await db.execute(sa.select(Invoice).where(Invoice.visit_id == visit_id))
    invoice = result.scalar_one_or_none()
    if invoice is None:
        # Invoices are created at registration (schema doc §3 0014), not
        # by this endpoint. A missing invoice means registration didn't
        # run — surfacing that beats silently creating one with no
        # registration line.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No invoice found for visit_id={visit_id}. Invoices are created at registration.",
        )
    return invoice


async def preview_invoice(db: AsyncSession, visit_id: uuid.UUID) -> InvoicePreviewResponse:
    """Read-only. Never writes to invoice_items or invoices."""
    result = await db.execute(sa.select(Invoice).where(Invoice.visit_id == visit_id))
    invoice = result.scalar_one_or_none()

    if invoice is None:
        new_lines: list[ChargeLine] = []
        already_billed = 0
        existing_gross = Decimal("0")
        invoice_id = None
        invoice_status = None
    else:
        new_lines = await aggregate_unbilled_charges(db, visit_id, invoice.id)
        count_result = await db.execute(
            sa.select(sa.func.count()).select_from(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
        )
        already_billed = count_result.scalar_one()
        existing_gross = Decimal(invoice.gross_amount)
        invoice_id = invoice.id
        invoice_status = invoice.status

    priced_total = sum((line.amount for line in new_lines if line.priced), Decimal("0"))
    unpriced_count = sum(1 for line in new_lines if not line.priced)

    return InvoicePreviewResponse(
        visit_id=visit_id,
        invoice_id=invoice_id,
        invoice_status=invoice_status,
        already_billed_count=already_billed,
        new_charge_lines=new_lines,
        unpriced_count=unpriced_count,
        projected_new_charges_total=_money(priced_total),
        projected_gross_amount=_money(existing_gross + priced_total),
    )


async def build_invoice(
    db: AsyncSession,
    visit_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    dry_run: bool = False,
) -> InvoiceBuildResponse:
    """
    Append unbilled, priced charge lines to the visit's draft invoice
    and recompute totals. No db.commit() here — see module docstring;
    app/common/db.get_db() commits once after the route handler returns.
    """
    invoice = await _get_invoice_for_visit(db, visit_id)

    if invoice.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Invoice {invoice.invoice_number} is '{invoice.status}', not 'draft' — "
                "new charges can no longer be appended. Corrections require a new invoice."
            ),
        )

    charge_lines = await aggregate_unbilled_charges(db, visit_id, invoice.id)
    priced_lines = [line for line in charge_lines if line.priced]
    skipped = len(charge_lines) - len(priced_lines)

    if dry_run or not priced_lines:
        return InvoiceBuildResponse(
            visit_id=visit_id,
            invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            status=invoice.status,
            lines_added=0,
            lines_skipped_unpriced=skipped,
            gross_amount=_money(Decimal(invoice.gross_amount)),
            net_amount=_money(Decimal(invoice.net_amount)),
        )

    for line in priced_lines:
        db.add(
            InvoiceItem(
                invoice_id=invoice.id,
                charge_category=line.charge_category,
                reference_type=line.reference_type,
                reference_id=line.reference_id,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                amount=line.amount,
            )
        )

    added_total = sum((line.amount for line in priced_lines), Decimal("0"))
    invoice.gross_amount = _money(Decimal(invoice.gross_amount) + added_total)
    # net = gross - discount - scheme_adjustment. Discount/scheme
    # adjustment aren't touched by the builder (separate workflow) —
    # this only re-derives net_amount from the now-larger gross_amount.
    invoice.net_amount = _money(
        invoice.gross_amount - Decimal(invoice.discount_amount) - Decimal(invoice.scheme_adjustment)
    )
    invoice.updated_by = actor_user_id

    # Flush now, inside this still-open transaction, so
    # trg_invoices_freeze / trg_invoice_items_freeze raise here — as a
    # real exception the caller sees — rather than only at the implicit
    # commit in get_db() after this function has already returned 200.
    await db.flush()

    # TODO(billing): call into app.audit once it exists and its owner
    # confirms the function name/signature. Not implemented here —
    # app/audit isn't built yet on any branch, so there's nothing real
    # to call. When it lands, this is a CRITICAL-sensitivity mutation
    # (invoice gross/net change + new invoice_items rows) and should be
    # logged with enough detail to answer "which charges were billed"
    # (reference_ids / charge_categories / new invoice_item ids), not
    # just a lines-added count — worth keeping in mind for whoever
    # designs that call, not something to solve from billing's side.

    await db.refresh(invoice)

    return InvoiceBuildResponse(
        visit_id=visit_id,
        invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        status=invoice.status,
        lines_added=len(priced_lines),
        lines_skipped_unpriced=skipped,
        gross_amount=_money(Decimal(invoice.gross_amount)),
        net_amount=_money(Decimal(invoice.net_amount)),
    )


# ---------------------------------------------------------------------
# PM-JAY eligibility — STUB. No DB access, no async needed.
# ---------------------------------------------------------------------

_PMJAY_STUB_CONFIG = {
    "enabled": True,
    "default_status": "not_determined",
}


def check_pmjay_eligibility(patient_id: uuid.UUID, visit_id: uuid.UUID) -> PMJAYEligibilityResponse:
    """STUB — does not call ABDM/PM-JAY. Always 'not_determined' unless
    disabled, routed through a config dict (not hardcoded) so a real
    eligibility table can replace it later without changing the
    response shape. Do not wire this into automatic scheme_adjustment
    on invoices — see schemas.py docstring on PMJAYEligibilityResponse."""
    if not _PMJAY_STUB_CONFIG["enabled"]:
        return PMJAYEligibilityResponse(
            patient_id=patient_id,
            visit_id=visit_id,
            eligibility_status="not_eligible",
            reason="PM-JAY eligibility check is disabled for this deployment.",
        )

    return PMJAYEligibilityResponse(
        patient_id=patient_id,
        visit_id=visit_id,
        eligibility_status=_PMJAY_STUB_CONFIG["default_status"],
        reason=(
            "PM-JAY eligibility is not yet verified automatically — this is "
            "a stub pending ABDM/PM-JAY beneficiary API integration. Front "
            "desk should verify the beneficiary card/ABHA manually."
        ),
    )


# =======================================================================
# Payments / refunds — B7-W3-01 (issue #188).
#
# Payments and refunds are append-only (trg_payments_block_update/_delete,
# trg_refunds_block_update/_delete — see the B7-W3-01 migration). This
# module NEVER issues db.execute(update(...)) or session.delete(...)
# against Payment/Refund rows, by design — every "correction" is a new
# row. The only mutation triggered from this section is Invoice.status
# (+ updated_by), which trg_invoices_freeze already permits regardless
# of invoice status (see models.py Invoice docstring).
# =======================================================================


async def _allocate_billing_number(
    db: AsyncSession, facility_id: uuid.UUID, counter_type: str, prefix: str
) -> str:
    """
    Gapless RCP-/RFD-<FACILITY>-<YYYYMMDD>-<SEQ5> numbering per schema
    doc §3 0014 (billing_counters, UNIQUE(facility_id, counter_type,
    counter_date)).

    The doc's literal instruction is "allocate with SELECT ... FOR
    UPDATE inside the same transaction". I've used INSERT ... ON
    CONFLICT DO UPDATE ... RETURNING instead: a plain SELECT FOR UPDATE
    only locks a row that already exists, and does nothing to prevent
    two concurrent first-payment-of-the-day transactions at the same
    facility from both trying to INSERT the counter row and hitting a
    unique-constraint race. The upsert below is atomic and still
    gapless-on-rollback (a rolled-back transaction never incremented
    last_value, so the next caller gets the same number) — but flag
    this for review if the team wants literal SELECT FOR UPDATE for
    consistency with wherever invoice_number is allocated (that code
    isn't in this module — invoices are created at registration, per
    _get_invoice_for_visit's docstring).
    """
    today = date.today()

    facility_code_row = await db.execute(
        sa.select(facilities_t.c.code).where(facilities_t.c.id == facility_id)
    )
    facility_code = facility_code_row.scalar_one_or_none()
    if facility_code is None:
        # Should be unreachable (facility_id is a NOT NULL FK on
        # invoices), but a billing_counters row keyed to a nonexistent
        # facility would be a bad enough data-integrity problem that
        # it's worth a real 500 with a clear message, not a KeyError.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"facility_id={facility_id} has no matching facilities row.",
        )

    upsert = (
        pg_insert(billing_counters_t)
        .values(
            facility_id=facility_id,
            counter_type=counter_type,
            counter_date=today,
            last_value=1,
        )
        .on_conflict_do_update(
            constraint="uq_billing_counters_facility_type_date",
            set_={"last_value": billing_counters_t.c.last_value + 1},
        )
        .returning(billing_counters_t.c.last_value)
    )
    result = await db.execute(upsert)
    sequence = result.scalar_one()

    return f"{prefix}-{facility_code}-{today:%Y%m%d}-{sequence:05d}"


async def _payment_totals_for_invoice(db: AsyncSession, invoice_id: uuid.UUID) -> tuple[Decimal, Decimal]:
    """(total successful payments, total refunds against those payments) for one invoice."""
    paid_result = await db.execute(
        sa.select(sa.func.coalesce(sa.func.sum(Payment.amount), 0)).where(
            Payment.invoice_id == invoice_id,
            Payment.status == PaymentStatus.SUCCESS.value,
        )
    )
    total_paid = Decimal(paid_result.scalar_one())

    refunded_result = await db.execute(
        sa.select(sa.func.coalesce(sa.func.sum(Refund.amount), 0))
        .select_from(Refund)
        .join(Payment, Payment.id == Refund.payment_id)
        .where(Payment.invoice_id == invoice_id)
    )
    total_refunded = Decimal(refunded_result.scalar_one())

    return total_paid, total_refunded


def _invoice_status_for_balance(net_amount: Decimal, net_paid: Decimal) -> str:
    if net_paid <= Decimal("0"):
        return "issued"
    if net_paid >= net_amount:
        return "paid"
    return "partially_paid"


async def record_payment(
    db: AsyncSession,
    invoice_id: uuid.UUID,
    body: PaymentCreate,
    actor_user_id: uuid.UUID,
) -> PaymentOut:
    """
    Insert one immutable payments row and move the invoice status
    forward (issued -> partially_paid -> paid). No db.commit() here —
    see module docstring; app/common/db.get_db() commits once after the
    route handler returns.
    """
    result = await db.execute(sa.select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No invoice found for invoice_id={invoice_id}.",
        )

    if invoice.status not in _PAYABLE_INVOICE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Invoice {invoice.invoice_number} is '{invoice.status}' — "
                f"payments can only be recorded while it's one of {_PAYABLE_INVOICE_STATUSES}."
            ),
        )

    total_paid, total_refunded = await _payment_totals_for_invoice(db, invoice.id)
    net_paid_so_far = total_paid - total_refunded
    remaining_balance = _money(Decimal(invoice.net_amount) - net_paid_so_far)

    amount = _money(body.amount)
    if amount > remaining_balance:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Payment amount {amount} exceeds the invoice's remaining "
                f"balance of {remaining_balance}."
            ),
        )

    receipt_number = await _allocate_billing_number(db, invoice.facility_id, "receipt", "RCP")
    if body.collected_at:
        # datetime.fromisoformat() only accepts a trailing 'Z' from
        # Python 3.11 onward (schema doc §4.2 mandates 'Z'-suffixed
        # UTC timestamps in every API payload) — normalize defensively
        # so this doesn't silently depend on the deployed Python
        # version.
        collected_at = datetime.fromisoformat(body.collected_at.replace("Z", "+00:00"))
    else:
        collected_at = datetime.now(timezone.utc)

    payment = Payment(
        receipt_number=receipt_number,
        invoice_id=invoice.id,
        amount=amount,
        currency=body.currency,
        mode=body.mode.value,
        status=PaymentStatus.SUCCESS.value,
        collected_by=actor_user_id,
        collected_at=collected_at,
        created_by=actor_user_id,
    )
    db.add(payment)

    new_net_paid = net_paid_so_far + amount
    invoice.status = _invoice_status_for_balance(Decimal(invoice.net_amount), new_net_paid)
    invoice.updated_by = actor_user_id

    # Flush now, inside this still-open transaction, so
    # trg_payments_block_update/_delete (which this code never
    # deliberately triggers) or any other constraint violation surfaces
    # here as a real exception, not silently at the implicit commit in
    # get_db() after this function has already returned 200 — same
    # reasoning as build_invoice() above.
    await db.flush()

    # TODO(billing): call into app.audit once it exists — payment
    # collection is explicitly an audit event (architecture doc §26.1)
    # and CRITICAL sync sensitivity (schema doc §37/§70). Not
    # implemented here for the same reason as build_invoice()'s TODO:
    # app/audit isn't built yet on any branch.

    await db.refresh(payment)

    return PaymentOut(
        id=payment.id,
        receipt_number=payment.receipt_number,
        invoice_id=payment.invoice_id,
        amount=Decimal(payment.amount),
        currency=payment.currency,
        mode=payment.mode,
        status=payment.status,
        collected_at=payment.collected_at.isoformat(),
    )


async def create_refund(
    db: AsyncSession,
    payment_id: uuid.UUID,
    body: RefundCreate,
    actor_user_id: uuid.UUID,
) -> RefundOut:
    """
    Insert one immutable refunds row (a reversal ledger entry — this
    NEVER edits the payments row it points at, per schema doc pg.21:
    "a refund never edits the payment") and re-derive the invoice's
    status from the new balance. No db.commit() here — see module
    docstring.
    """
    result = await db.execute(sa.select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No payment found for payment_id={payment_id}.",
        )

    if payment.status != PaymentStatus.SUCCESS.value:
        # payments.status is never flipped by this module (see
        # PaymentCreate — it's always written as 'success'), so in
        # practice this branch only guards against a payment row that
        # was seeded with status='reversed' some other way (e.g. a data
        # migration/import). Kept as a real check rather than assumed
        # away, since it's a one-line guard against refunding something
        # that's already flagged as not a live success.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Payment {payment.receipt_number} has status '{payment.status}', not 'success' — cannot refund.",
        )

    already_refunded_result = await db.execute(
        sa.select(sa.func.coalesce(sa.func.sum(Refund.amount), 0)).where(Refund.payment_id == payment.id)
    )
    already_refunded = Decimal(already_refunded_result.scalar_one())
    refundable_balance = _money(Decimal(payment.amount) - already_refunded)

    amount = _money(body.amount)
    if amount > refundable_balance:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Refund amount {amount} exceeds payment {payment.receipt_number}'s "
                f"un-refunded balance of {refundable_balance}."
            ),
        )

    invoice_result = await db.execute(sa.select(Invoice).where(Invoice.id == payment.invoice_id))
    invoice = invoice_result.scalar_one_or_none()
    if invoice is None:  # pragma: no cover — FK guarantees this, defensive only
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment {payment.id} has no matching invoice (invoice_id={payment.invoice_id}).",
        )

    refund_number = await _allocate_billing_number(db, invoice.facility_id, "refund", "RFD")

    refund = Refund(
        refund_number=refund_number,
        payment_id=payment.id,
        amount=amount,
        reason=body.reason,
        approved_by=actor_user_id,
        refunded_at=datetime.now(timezone.utc),
        created_by=actor_user_id,
    )
    db.add(refund)

    total_paid, total_refunded = await _payment_totals_for_invoice(db, invoice.id)
    new_net_paid = total_paid - (total_refunded + amount)
    invoice.status = _invoice_status_for_balance(Decimal(invoice.net_amount), new_net_paid)
    invoice.updated_by = actor_user_id

    # Same reasoning as record_payment() above — flush inside this
    # still-open transaction so any trigger/constraint issue surfaces
    # as a real exception now.
    await db.flush()

    # TODO(billing): call into app.audit once it exists — same note as
    # record_payment(); refunds are the more sensitive of the two
    # (billing_refunds module gate, approved_by field) so this matters
    # at least as much when app/audit lands.

    await db.refresh(refund)

    return RefundOut(
        id=refund.id,
        refund_number=refund.refund_number,
        payment_id=refund.payment_id,
        amount=Decimal(refund.amount),
        reason=refund.reason,
        approved_by=refund.approved_by,
        refunded_at=refund.refunded_at.isoformat(),
    )

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

AUDIT LOGGING — wired in (issue #290, B7 rollout item). app/audit lives
on `staging` (PR #261) and is pulled into this branch via
`git merge origin/staging`. Invoice opts into the automatic
before_flush/after_flush hook in app/audit/listeners.py (see
models.Invoice's docstring) — every status/gross_amount/net_amount
change from build_invoice()/record_payment()/create_refund() is
captured for free, no call needed here for that part.
invoice_items/payments/refunds have no facility_id column of their own
(reached only via invoice_id/payment_id), so they cannot use that same
automatic hook — their creation is logged with a direct, manual call to
app.audit.service.write_audit_log() at the point each row is added
below, using the invoice's own facility_id (already in scope) and the
per-request actor populated by app.audit.deps.get_current_actor_dependency
(wired into router.py on the three mutating endpoints). This is the
architecturally-correct manual path per app/audit/service.py's own
docstring ("use this for ... anything that bypasses the automatic
hook"), not a workaround.

BRANCH NOTE: if `import app.billing.service` (or router) ever raises
`ModuleNotFoundError: No module named 'app.audit...'`, that means this
checkout has fallen behind staging, not that the wiring below is wrong
— run `git merge origin/staging` first. Do not strip this back out to
"fix" that error; app/audit genuinely exists, it just needs pulling in.

PR REVIEW FIX (blocker 2 — concurrent invoice builds could double-bill):
_already_billed_reference_ids() below is still read-then-write and is
still a real race on its own — the actual fix is a partial UNIQUE index
on invoice_items(invoice_id, reference_type, reference_id), landing in
migration 0033 (#285, owned by solutionsiui) alongside charge_master.
Until this repo rebases onto that migration, _insert_invoice_item()
wraps each line's insert in its own SAVEPOINT (db.begin_nested()) so
that if two concurrent build_invoice() calls do race past the app-level
check, at least the failure mode is "one line silently not
double-added" rather than "500, and the whole batch's flush aborts".
Once 0033's unique index lands, the same except-block starts catching
IntegrityError for a real reason (constraint violation) instead of
never firing at all — no further code change needed here, per review:
"Keep your app-level check as a fast path, but let the database be
what makes it true, and handle the conflict as a no-op rather than a
500."
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.audit.service import write_audit_log
from app.billing.models import Invoice, InvoiceItem, Payment, Refund
from app.billing.pricing import (
    price_lab_test,
    price_pharmacy_batch,
    price_radiology_modality,
)
from app.billing.schemas import (
    ChargeLine,
    DailyRevenuePoint,
    DailyRevenueResponse,
    InvoiceBuildResponse,
    InvoicePreviewResponse,
    PaymentCreate,
    PaymentOut,
    PendingInvoiceLine,
    PendingInvoicesResponse,
    PMJAYEligibilityResponse,
    RefundCreate,
    RefundOut,
    SchemeBreakdownLine,
    SchemeBreakdownResponse,
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
users_t = sa.table("users", sa.column("id"), sa.column("keycloak_sub"), sa.column("facility_id"))

# idempotency_keys (0002, owned by B1) — shared infra table, read/write only,
# no schema change made here. §4A.1: every POST that creates something needs
# an Idempotency-Key; enforced for payments/refunds in router.py.
idempotency_keys_t = sa.table(
    "idempotency_keys",
    sa.column("key"), sa.column("endpoint"), sa.column("request_hash"),
    sa.column("response_status"), sa.column("response_body"), sa.column("user_id"),
)

# facilities.code (varchar(20), e.g. "JPR001") — schema doc §3 0002.
# Needed to format receipt_number / refund_number
# (RCP-<FACILITY>-<YYYYMMDD>-<SEQ5> / RFD-...). Same cross-module
# read-only-projection approach as the tables above.
facilities_t = sa.table("facilities", sa.column("id"), sa.column("code"), sa.column("timezone"))


async def _facility_business_date(db: AsyncSession, facility_id: uuid.UUID) -> date:
    """(now() AT TIME ZONE facilities.timezone)::date — per schema doc's blanket
    rule. NEVER use date.today() / now()::date for a business date: that's UTC,
    and IST is UTC+5:30, so anything before 05:30 IST lands on yesterday."""
    result = await db.execute(
        sa.select(sa.cast(sa.func.timezone(facilities_t.c.timezone, sa.func.now()), sa.Date))
        .where(facilities_t.c.id == facility_id)
    )
    business_date = result.scalar_one_or_none()
    if business_date is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"facility_id={facility_id} not found.")
    return business_date

# billing_counters — gapless allocator (schema doc §3 0014). Real model
# is app.billing.models.BillingCounter; using a bare table projection
# here too since the allocation query below is an INSERT..ON CONFLICT
# upsert, not something the ORM layer buys us anything for.
billing_counters_t = sa.table(
    "billing_counters",
    sa.column("facility_id"), sa.column("counter_type"),
    sa.column("counter_date"), sa.column("last_value"),
)

# charge_master (0033) — effective-dated tariff. Table has existed since 0033
# with no ORM model and no reader; #389 makes registration its first consumer.
charge_master_t = sa.table(
    "charge_master",
    sa.column("id"), sa.column("facility_id"), sa.column("charge_code"),
    sa.column("charge_category"), sa.column("description"), sa.column("unit_price"),
    sa.column("scheme_code"), sa.column("effective_from"), sa.column("effective_to"),
    sa.column("is_active"),
)

#: The tariff row every facility must have for registration to price its invoice.
#: Seeds and facility onboarding both depend on this exact string.
REGISTRATION_CHARGE_CODE = "REGISTRATION"

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


async def _insert_invoice_item(db: AsyncSession, line: "ChargeLine", invoice_id: uuid.UUID) -> bool:
    """
    Insert one InvoiceItem inside its own SAVEPOINT. Returns True if the
    line was actually added, False if it was skipped as a (likely
    concurrent) duplicate.

    See module docstring re: blocker #2. The constraint backing this is
    uq_invoice_items_invoice_reference — a partial UNIQUE index on
    (invoice_id, reference_type, reference_id) WHERE reference_id IS NOT
    NULL, added in 0014 alongside the table. It was originally deferred to
    a later migration, which left this except-block unable to fire: two
    concurrent build_invoice() calls would both insert the same charge and
    bill the patient twice. test_two_concurrent_builds_bill_each_charge_at
    _most_once is what catches that, and it was failing.

    The SAVEPOINT matters: one duplicate line rolls back on its own
    without aborting the rest of this build_invoice() call's flush.
    """
    try:
        async with db.begin_nested():
            db.add(
                InvoiceItem(
                    invoice_id=invoice_id,
                    charge_category=line.charge_category,
                    reference_type=line.reference_type,
                    reference_id=line.reference_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    amount=line.amount,
                )
            )
            await db.flush()
    except IntegrityError:
        return False
    return True


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

    added_lines: list[ChargeLine] = []
    for line in priced_lines:
        was_added = await _insert_invoice_item(db, line, invoice.id)
        if was_added:
            added_lines.append(line)
        else:
            skipped += 1  # lost the concurrent race — another call billed this reference_id first

    if not added_lines:
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

    added_total = sum((line.amount for line in added_lines), Decimal("0"))
    invoice.gross_amount = _money(Decimal(invoice.gross_amount) + added_total)
    # net = gross - discount - scheme_adjustment. Discount/scheme
    # adjustment aren't touched by the builder (separate workflow) —
    # this only re-derives net_amount from the now-larger gross_amount.
    invoice.net_amount = _money(
        invoice.gross_amount - Decimal(invoice.discount_amount) - Decimal(invoice.scheme_adjustment)
    )
    invoice.updated_by = actor_user_id
    invoice.row_version = invoice.row_version + 1

    # Flush now, inside this still-open transaction, so
    # trg_invoices_freeze / trg_invoice_items_freeze raise here — as a
    # real exception the caller sees — rather than only at the implicit
    # commit in get_db() after this function has already returned 200.
    await db.flush()

    # Manual audit — invoice_items has no facility_id column, so it
    # can't opt into app/audit/listeners.py's automatic hook (see
    # models.py docstrings). The Invoice UPDATE itself (gross/net_amount
    # change above) IS captured automatically since Invoice opted in —
    # this call is only for the new invoice_items rows, so "which
    # charges were billed" (reference_ids/charge_categories) is on
    # record, not just a lines-added count.
    await write_audit_log(
        db,
        facility_id=invoice.facility_id,
        action=AuditAction.CREATE,
        resource_type="invoice_items",
        user_id=actor_user_id,
        resource_id=invoice.id,
        patient_id=invoice.patient_id,
        visit_id=invoice.visit_id,
        new_value={
            "invoice_id": str(invoice.id),
            "lines_added": len(added_lines),
            "added_total": str(added_total),
            "charge_lines": [
                {
                    "charge_category": getattr(line.charge_category, "value", line.charge_category),
                    "reference_type": line.reference_type,
                    "reference_id": str(line.reference_id),
                    "amount": str(line.amount),
                }
                for line in added_lines
            ],
        },
    )

    await db.refresh(invoice)

    return InvoiceBuildResponse(
        visit_id=visit_id,
        invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        status=invoice.status,
        lines_added=len(added_lines),
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
    db: AsyncSession,
    facility_id: uuid.UUID,
    counter_type: str,
    prefix: str,
    *,
    business_date: date | None = None,
) -> str:
    """
    Gapless INV-/RCP-/RFD-<FACILITY>-<YYYYMMDD>-<SEQ5> numbering per schema
    doc §3 0014 (billing_counters, UNIQUE(facility_id, counter_type,
    counter_date)).

    `business_date` is the caller's already-computed facility-local date. Pass
    it whenever the caller has one: registration allocates a visit number and an
    invoice number for the same event, and two independent clock reads can
    straddle midnight and stamp them with different dates. Omit it and this
    reads the clock itself, which is correct for standalone receipt and refund
    numbering. Same rule as opd/visit_number.py — one business_date per request,
    computed once and threaded through.

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
    facility_row = await db.execute(
        sa.select(
            facilities_t.c.code,
            sa.cast(sa.func.timezone(facilities_t.c.timezone, sa.func.now()), sa.Date).label("business_date"),
        ).where(facilities_t.c.id == facility_id)
    )
    row = facility_row.first()
    if row is None:
        # Should be unreachable (facility_id is a NOT NULL FK on
        # invoices), but a billing_counters row keyed to a nonexistent
        # facility would be a bad enough data-integrity problem that
        # it's worth a real 500 with a clear message, not a KeyError.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"facility_id={facility_id} has no matching facilities row.",
        )
    # The caller's date wins when supplied — see the docstring on why two
    # independent reads of "today" must not be allowed to disagree.
    facility_code = row.code
    today = business_date if business_date is not None else row.business_date

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


async def registration_charge(
    db: AsyncSession, facility_id: uuid.UUID, business_date: date
) -> sa.Row | None:
    """The tariff in force for registration at this facility on this date.

    Effective-dated: `effective_from <= date < effective_to`, with an open
    `effective_to` meaning "still current". Ordered newest-first so a
    superseding row wins if two overlap — 0033's ck_charge_master_effective_range
    guarantees each row is internally sane but not that two rows cannot overlap.

    The date must be the caller's business date, not `now()`. A patient
    registering at 01:00 IST is registering on today's tariff, and a bare
    date read here would give them yesterday's.
    """
    result = await db.execute(
        sa.select(
            charge_master_t.c.id,
            charge_master_t.c.unit_price,
            charge_master_t.c.description,
            charge_master_t.c.charge_category,
        )
        .where(
            charge_master_t.c.facility_id == facility_id,
            charge_master_t.c.charge_code == REGISTRATION_CHARGE_CODE,
            charge_master_t.c.is_active.is_(True),
            charge_master_t.c.effective_from <= business_date,
            sa.or_(
                charge_master_t.c.effective_to.is_(None),
                charge_master_t.c.effective_to >= business_date,
            ),
        )
        .order_by(charge_master_t.c.effective_from.desc())
        .limit(1)
    )
    return result.first()


async def create_registration_invoice(
    db: AsyncSession,
    *,
    visit_id: uuid.UUID,
    patient_id: uuid.UUID,
    facility_id: uuid.UUID,
    business_date: date,
    created_by: uuid.UUID,
) -> Invoice:
    """The one invoice per visit that §3 0014 has always promised.

    Called by opd.create_visit inside the registration transaction, so a visit
    and its invoice are created together or not at all. Everything downstream —
    preview, build, payment posting, billing MIS — assumes this row exists;
    `_get_invoice_for_visit` 404s without it. Until #389 nothing created one, so
    the entire billing chain had no entry point.

    Raises 409 when the facility has no active REGISTRATION tariff. That fails
    registration, which is deliberate: the alternative is a zero-rupee invoice
    that looks legitimate and is discovered at month-end reconciliation. A
    missing tariff is a five-minute configuration fix; a quarter of mispriced
    invoices is not.
    """
    charge = await registration_charge(db, facility_id, business_date)
    if charge is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "registration_tariff_not_configured",
                "message": (
                    f"No active '{REGISTRATION_CHARGE_CODE}' row in charge_master for "
                    f"facility_id={facility_id} effective {business_date}. Add the tariff "
                    f"before registering patients at this facility."
                ),
            },
        )

    amount = Decimal(charge.unit_price)
    invoice_number = await _allocate_billing_number(
        db, facility_id, "invoice", "INV", business_date=business_date
    )

    invoice = Invoice(
        id=uuid.uuid4(),
        invoice_number=invoice_number,
        visit_id=visit_id,
        patient_id=patient_id,
        facility_id=facility_id,
        status="draft",
        gross_amount=amount,
        discount_amount=Decimal("0"),
        scheme_adjustment=Decimal("0"),
        net_amount=amount,
        created_by=created_by,
    )
    db.add(invoice)
    await db.flush()

    db.add(
        InvoiceItem(
            id=uuid.uuid4(),
            invoice_id=invoice.id,
            charge_category=charge.charge_category,
            description=charge.description,
            quantity=Decimal("1"),
            unit_price=amount,
            amount=amount,
            charge_master_id=charge.id,
        )
    )
    await db.flush()
    return invoice


async def _facility_timezone(db: AsyncSession, facility_id: uuid.UUID) -> str:
    result = await db.execute(sa.select(facilities_t.c.timezone).where(facilities_t.c.id == facility_id))
    return result.scalar_one()


async def _payment_totals_for_invoice(db: AsyncSession, invoice_id: uuid.UUID) -> tuple[Decimal, Decimal]:
    """(total successful payments, total refunds against those payments) for one invoice.

    BUG FIX: this function's `async def` line was missing in the
    reviewed snapshot — its body had been left dangling as unreachable
    dead code inside _facility_timezone() (after that function's own
    `return`), and `_payment_totals_for_invoice` was called from three
    places (record_payment, create_refund, get_pending_invoices) with no
    matching definition anywhere in the module. That's a NameError on
    first call, not caught by import-time checks — restored as its own
    function here.
    """
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
    result = await db.execute(sa.select(Invoice).where(Invoice.id == invoice_id).with_for_update())
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
    invoice.row_version = invoice.row_version + 1

    # Flush now, inside this still-open transaction, so
    # trg_payments_block_update/_delete (which this code never
    # deliberately triggers) or any other constraint violation surfaces
    # here as a real exception, not silently at the implicit commit in
    # get_db() after this function has already returned 200 — same
    # reasoning as build_invoice() above.
    await db.flush()

    # Manual audit — payments has no facility_id column, so it can't
    # opt into app/audit/listeners.py's automatic hook (see models.py).
    # Payment collection is explicitly an audit event (architecture doc
    # §26.1) and CRITICAL sync sensitivity (schema doc §37/§70).
    # The Invoice status transition above IS captured automatically
    # since Invoice opted in — this call covers the payment row itself.
    await write_audit_log(
        db,
        facility_id=invoice.facility_id,
        action=AuditAction.CREATE,
        resource_type="payments",
        user_id=actor_user_id,
        resource_id=payment.id,
        patient_id=invoice.patient_id,
        visit_id=invoice.visit_id,
        new_value={
            "receipt_number": payment.receipt_number,
            "invoice_id": str(invoice.id),
            "amount": str(payment.amount),
            "mode": payment.mode,
            "invoice_status_after": invoice.status,
        },
    )

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
    result = await db.execute(sa.select(Payment).where(Payment.id == payment_id).with_for_update())
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
    invoice.row_version = invoice.row_version + 1

    # Same reasoning as record_payment() above — flush inside this
    # still-open transaction so any trigger/constraint issue surfaces
    # as a real exception now.
    await db.flush()

    # Manual audit — refunds has no facility_id column, so it can't
    # opt into app/audit/listeners.py's automatic hook (see models.py).
    # Refunds are the more sensitive of the two events (core/always-on
    # per v3.13, carries approved_by) so this matters at least as much
    # as the payment-side call in record_payment(). The Invoice status
    # transition above IS captured automatically since Invoice opted in
    # — this call covers the refund row itself.
    await write_audit_log(
        db,
        facility_id=invoice.facility_id,
        action=AuditAction.CREATE,
        resource_type="refunds",
        user_id=actor_user_id,
        resource_id=refund.id,
        patient_id=invoice.patient_id,
        visit_id=invoice.visit_id,
        reason=body.reason,
        new_value={
            "refund_number": refund.refund_number,
            "payment_id": str(payment.id),
            "amount": str(refund.amount),
            "approved_by": str(actor_user_id),
            "invoice_status_after": invoice.status,
        },
    )

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


# =======================================================================
# Billing MIS — B7-W3-02 (#189). Read-only. Computed live from
# invoices/payments/refunds, not kpi_snapshots (that's B1's daily-job
# table — separate concern). Every function here is facility-scoped;
# router resolves the caller's own facility_id, never a client-supplied one.
# =======================================================================


async def facility_id_for_user(db: AsyncSession, keycloak_sub: str) -> uuid.UUID:
    result = await db.execute(sa.select(users_t.c.facility_id).where(users_t.c.keycloak_sub == keycloak_sub))
    facility_id = result.scalar_one_or_none()
    if facility_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No users row matches this token's subject.")
    return facility_id


def _request_hash(request_body: dict) -> str:
    canonical = json.dumps(request_body, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def check_idempotency(
    db: AsyncSession, key: str, endpoint: str, request_body: dict, user_id: uuid.UUID
) -> dict | None:
    """None = unseen, proceed normally. Returns the cached response body to
    replay if this exact key+endpoint+body was already handled. Raises 409
    idempotency_key_reuse if the same key was used with a different body.

    Scoped by user_id as well as key and endpoint — that is the real unique
    key (0003a: UNIQUE (key, user_id, endpoint)). Keys are client-generated,
    so two users can legitimately emit the same one against the same
    endpoint; matching on key+endpoint alone would replay the FIRST user's
    stored response to the second. §4A.1 stated the wrong unique key until
    today, which is where this came from."""
    result = await db.execute(
        sa.select(idempotency_keys_t.c.request_hash, idempotency_keys_t.c.response_body)
        .where(
            idempotency_keys_t.c.key == key,
            idempotency_keys_t.c.user_id == user_id,
            idempotency_keys_t.c.endpoint == endpoint,
        )
    )
    row = result.first()
    if row is None:
        return None
    if row.request_hash != _request_hash(request_body):
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "idempotency_key_reuse"})
    return row.response_body


async def store_idempotency(
    db: AsyncSession, key: str, endpoint: str, request_body: dict, user_id: uuid.UUID,
    response_body: dict, response_status: int = 201,
) -> None:
    await db.execute(
        pg_insert(idempotency_keys_t)
        .values(
            key=key, endpoint=endpoint, request_hash=_request_hash(request_body),
            response_status=response_status, response_body=response_body, user_id=user_id,
        )
        # Must match a real unique index or Postgres raises "no unique or
        # exclusion constraint matching the ON CONFLICT specification" —
        # a 500 on every stored payment, not a silent mismatch. 0003a's
        # constraint is (key, user_id, endpoint).
        .on_conflict_do_nothing(
            index_elements=["key", "user_id", "endpoint"]
        )
    )


async def get_daily_revenue(
    db: AsyncSession, facility_id: uuid.UUID, date_from: date | None, date_to: date | None
) -> DailyRevenueResponse:
    """Net revenue = cash collected minus cash refunded, per facility business
    day (each side counted on the day it happened, not the original payment's
    day). Bucketed via facilities.timezone, not UTC — see _facility_business_date."""
    business_today = await _facility_business_date(db, facility_id)
    date_from = date_from or business_today
    date_to = date_to or business_today
    if date_from > date_to:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "date_from must be <= date_to.")

    tz_row = await db.execute(sa.select(facilities_t.c.timezone).where(facilities_t.c.id == facility_id))
    tz = tz_row.scalar_one()
    paid_day = sa.cast(sa.func.timezone(tz, Payment.collected_at), sa.Date)
    refund_day = sa.cast(sa.func.timezone(tz, Refund.refunded_at), sa.Date)

    paid_rows = await db.execute(
        sa.select(
            paid_day.label("day"),
            sa.func.count().label("cnt"),
            sa.func.sum(Payment.amount).label("total"),
        )
        .select_from(Payment)
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .where(
            Invoice.facility_id == facility_id,
            Payment.status == PaymentStatus.SUCCESS.value,
            paid_day.between(date_from, date_to),
        )
        .group_by(paid_day)
    )
    paid_by_day = {row.day: (row.cnt, Decimal(row.total)) for row in paid_rows}

    refund_rows = await db.execute(
        sa.select(
            refund_day.label("day"),
            sa.func.sum(Refund.amount).label("total"),
        )
        .select_from(Refund)
        .join(Payment, Payment.id == Refund.payment_id)
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .where(
            Invoice.facility_id == facility_id,
            refund_day.between(date_from, date_to),
        )
        .group_by(refund_day)
    )
    refunded_by_day = {row.day: Decimal(row.total) for row in refund_rows}

    points: list[DailyRevenuePoint] = []
    total_net = Decimal("0")
    day = date_from
    while day <= date_to:
        cnt, gross = paid_by_day.get(day, (0, Decimal("0")))
        refunded = refunded_by_day.get(day, Decimal("0"))
        net = _money(gross - refunded)
        total_net += net
        points.append(
            DailyRevenuePoint(
                day=day, payment_count=cnt, gross_collected=_money(gross),
                refunded=_money(refunded), net_revenue=net,
            )
        )
        day = date.fromordinal(day.toordinal() + 1)

    return DailyRevenueResponse(
        facility_id=facility_id, date_from=date_from, date_to=date_to,
        points=points, total_net_revenue=_money(total_net),
    )


async def get_pending_invoices(db: AsyncSession, facility_id: uuid.UUID) -> PendingInvoicesResponse:
    """Invoices with status in (issued, partially_paid) i.e. balance_due > 0."""
    result = await db.execute(
        sa.select(Invoice).where(
            Invoice.facility_id == facility_id,
            Invoice.status.in_(_PAYABLE_INVOICE_STATUSES),
        ).order_by(Invoice.created_at.asc())
    )
    invoices = result.scalars().all()

    business_today = await _facility_business_date(db, facility_id)
    tz = ZoneInfo(await _facility_timezone(db, facility_id))
    items: list[PendingInvoiceLine] = []
    total_balance = Decimal("0")
    for invoice in invoices:
        total_paid, total_refunded = await _payment_totals_for_invoice(db, invoice.id)
        paid_amount = _money(total_paid - total_refunded)
        balance_due = _money(Decimal(invoice.net_amount) - paid_amount)
        if balance_due <= Decimal("0"):  # fully paid, status just hasn't caught up somehow — skip
            continue
        total_balance += balance_due
        items.append(
            PendingInvoiceLine(
                invoice_id=invoice.id,
                invoice_number=invoice.invoice_number,
                visit_id=invoice.visit_id,
                patient_id=invoice.patient_id,
                status=invoice.status,
                net_amount=_money(Decimal(invoice.net_amount)),
                paid_amount=paid_amount,
                balance_due=balance_due,
                created_at=invoice.created_at.isoformat(),
                days_pending=(business_today - invoice.created_at.astimezone(tz).date()).days,
            )
        )

    return PendingInvoicesResponse(
        facility_id=facility_id,
        as_of=datetime.now(timezone.utc).isoformat(),
        count=len(items),
        total_balance_due=_money(total_balance),
        items=items,
    )


async def get_scheme_breakdown(
    db: AsyncSession, facility_id: uuid.UUID, date_from: date | None, date_to: date | None
) -> SchemeBreakdownResponse:
    """Groups invoices created in [date_from, date_to] (facility-local dates)
    by scheme_code (NULL -> 'self_pay'). collected_total nets out refunds,
    same as get_daily_revenue."""
    business_today = await _facility_business_date(db, facility_id)
    date_from = date_from or business_today
    date_to = date_to or business_today
    if date_from > date_to:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "date_from must be <= date_to.")

    tz = await _facility_timezone(db, facility_id)
    invoice_day = sa.cast(sa.func.timezone(tz, Invoice.created_at), sa.Date)

    scheme_col = sa.func.coalesce(Invoice.scheme_code, "self_pay").label("scheme_code")
    result = await db.execute(
        sa.select(
            scheme_col,
            sa.func.count().label("cnt"),
            sa.func.sum(Invoice.net_amount).label("net_billed"),
            sa.func.sum(Invoice.scheme_adjustment).label("scheme_adjustment"),
        )
        .where(
            Invoice.facility_id == facility_id,
            invoice_day.between(date_from, date_to),
        )
        .group_by(scheme_col)
    )
    rows = result.all()

    lines: list[SchemeBreakdownLine] = []
    grand_total = Decimal("0")
    for row in rows:
        scheme_filter = None if row.scheme_code == "self_pay" else row.scheme_code

        collected_result = await db.execute(
            sa.select(sa.func.coalesce(sa.func.sum(Payment.amount), 0))
            .select_from(Payment)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .where(
                Invoice.facility_id == facility_id,
                Invoice.scheme_code == scheme_filter,
                invoice_day.between(date_from, date_to),
                Payment.status == PaymentStatus.SUCCESS.value,
            )
        )
        refunded_result = await db.execute(
            sa.select(sa.func.coalesce(sa.func.sum(Refund.amount), 0))
            .select_from(Refund)
            .join(Payment, Payment.id == Refund.payment_id)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .where(
                Invoice.facility_id == facility_id,
                Invoice.scheme_code == scheme_filter,
                invoice_day.between(date_from, date_to),
            )
        )
        collected = _money(Decimal(collected_result.scalar_one()) - Decimal(refunded_result.scalar_one()))
        net_billed = _money(Decimal(row.net_billed))
        grand_total += net_billed
        lines.append(
            SchemeBreakdownLine(
                scheme_code=row.scheme_code,
                invoice_count=row.cnt,
                net_billed=net_billed,
                scheme_adjustment_total=_money(Decimal(row.scheme_adjustment)),
                collected_total=collected,
            )
        )

    return SchemeBreakdownResponse(
        facility_id=facility_id, date_from=date_from, date_to=date_to,
        lines=lines, grand_total_net_billed=_money(grand_total),
    )

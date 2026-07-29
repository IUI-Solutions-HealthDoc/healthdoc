"""
Invoice builder service (B7-W2-01 — issue #168).

REVISED after seeing app/common/: this stack is fully async
(AsyncSession / asyncpg via db.py), so every DB-touching function here
is async and every db.execute(...) is awaited.

app/common/db.get_db() already commits once, automatically, after the
route handler returns — so this module never calls db.commit() itself.
It calls db.flush() before building the response so that
trg_invoices_freeze / trg_invoice_items_freeze errors (if the guard
below somehow missed a race) surface as a real exception now, not as a
silent no-op discovered later, and db.refresh() to read back
server-computed values within the same still-open transaction.

Status/category values come from app/common/enums.py (ResultStatus,
DispenseStatus, ChargeCategory) instead of inline strings, per that
file's own "never inline strings" rule.

AUDIT LOGGING — intentionally NOT wired in this file. app/audit isn't
implemented yet and nothing on the team has merged anything for it, so
there's no real function, confirmed signature, or confirmed table
shape to call into. Left as a single TODO comment at the call site in
build_invoice() — pick it up once app/audit exists and its owner
confirms the interface. Not adding a fallback/stub import here on
purpose: that's speculative code for an unmerged module in someone
else's folder, not this ticket's job.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Invoice, InvoiceItem
from app.billing.pricing import (
    price_lab_test,
    price_pharmacy_batch,
    price_radiology_modality,
)
from app.billing.schemas import (
    ChargeLine,
    InvoiceBuildResponse,
    InvoicePreviewResponse,
    PMJAYEligibilityResponse,
)
from app.common.enums import ChargeCategory, DispenseStatus, ResultStatus

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

# A corrected result still means the work is complete/billable — the
# correction itself doesn't un-bill the earlier line (that's a
# refund/dispute concern, out of scope here).
_LAB_BILLABLE_STATUSES = (ResultStatus.FINAL.value, ResultStatus.CORRECTED.value)
_RADIOLOGY_BILLABLE_STATUSES = (ResultStatus.FINAL.value, ResultStatus.CORRECTED.value)
_PHARMACY_BILLABLE_STATUSES = (DispenseStatus.DISPENSED.value, DispenseStatus.PARTIALLY_DISPENSED.value)


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

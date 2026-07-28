"""
Invoice builder service (B7-W2-01 — issue #168).

WHAT THIS DOES
---------------
Given a visit, find chargeable clinical work that has completed but
has no matching invoice_items row yet, price it, and either:
  - report it back without writing anything (preview), or
  - append it to the visit's draft invoice as new invoice_items rows
    (build).

Also ships a PM-JAY eligibility STUB (see docstring on
check_pmjay_eligibility below).

WHY invoice_items IS THE DEDUPE KEY, NOT A "billed" FLAG ON THE SOURCE
ROW
------------------------------------------------------------------
lab_order_items / radiology_order_items / pharmacy_dispense_items
don't have a "billed" boolean, and I'm not adding one to their tables
in this module. invoice_items.reference_type + reference_id already
exists for exactly this purpose (schema doc §3 0014: "reference_id —
source row"), so "already billed" is answered by
    NOT EXISTS (SELECT 1 FROM invoice_items
                WHERE reference_type = <table> AND reference_id = <row.id>)
This also makes the builder idempotent — calling /build twice in a row
is a no-op the second time, which matters because departments append
work continuously and this endpoint will be polled/retried.

WHAT'S DELIBERATELY NOT HANDLED YET (flagged, not silently skipped)
------------------------------------------------------------------
- ipd_stay (per-day bed charges) and procedure (OT) charges: both need
  a rate basis (ward/bed-class tariff, OT package pricing) that
  doesn't exist in the schema yet. Left out rather than guessed.
- blood: same reasoning (blood_units has no price column).
These three charge_category values still exist on invoice_items for
when someone (possibly me, in a follow-up ticket) adds their
aggregators; this file only wires lab/radiology/pharmacy.

Cross-module tables (visits, encounters, orders, lab_*, radiology_*,
pharmacy_*, inventory_batches) are read here via lightweight
sqlalchemy.sql.table() projections rather than importing other
modules' ORM models, to avoid a hard import dependency between
app/billing and app/{lab,radiology,pharmacy,visits}. If those modules
already export their ORM models for cross-module use by the time this
merges, swap these for real model imports — same queries, less
duplication.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

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
from app.common.exceptions import ConflictError, NotFoundError

TWO_PLACES = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------
# Minimal read-only projections of cross-module tables. Column lists
# are intentionally narrow — only what this file needs.
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

# "final" also covers a corrected result — a corrected report still
# means the work is complete and billable; the correction itself
# doesn't un-bill the earlier line (that's a refund/dispute concern,
# out of scope here).
_LAB_BILLABLE_STATUSES = ("final", "corrected")
_RADIOLOGY_BILLABLE_STATUSES = ("final", "corrected")
_PHARMACY_BILLABLE_STATUSES = ("dispensed", "partially_dispensed")


def _already_billed_reference_ids(db: Session, invoice_id: uuid.UUID, reference_type: str) -> set[uuid.UUID]:
    rows = db.execute(
        sa.select(InvoiceItem.reference_id).where(
            InvoiceItem.invoice_id == invoice_id,
            InvoiceItem.reference_type == reference_type,
        )
    ).scalars().all()
    return set(rows)


def _aggregate_lab_charges(db: Session, visit_id: uuid.UUID, invoice_id: uuid.UUID) -> list[ChargeLine]:
    billed = _already_billed_reference_ids(db, invoice_id, "lab_order_items")

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

    lines: list[ChargeLine] = []
    for row in db.execute(stmt):
        if row.id in billed:
            continue
        price = price_lab_test(row.test_code)
        unit_price = price.unit_price if price.unit_price is not None else Decimal("0")
        lines.append(
            ChargeLine(
                charge_category="lab",
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


def _aggregate_radiology_charges(db: Session, visit_id: uuid.UUID, invoice_id: uuid.UUID) -> list[ChargeLine]:
    billed = _already_billed_reference_ids(db, invoice_id, "radiology_order_items")

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

    lines: list[ChargeLine] = []
    for row in db.execute(stmt):
        if row.id in billed:
            continue
        price = price_radiology_modality(row.modality)
        unit_price = price.unit_price if price.unit_price is not None else Decimal("0")
        lines.append(
            ChargeLine(
                charge_category="radiology",
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


def _aggregate_pharmacy_charges(db: Session, visit_id: uuid.UUID, invoice_id: uuid.UUID) -> list[ChargeLine]:
    billed = _already_billed_reference_ids(db, invoice_id, "pharmacy_dispense_items")

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

    lines: list[ChargeLine] = []
    for row in db.execute(stmt):
        if row.id in billed:
            continue
        price = price_pharmacy_batch(row.issue_rate_mrp)
        qty = Decimal(row.quantity_dispensed)
        unit_price = price.unit_price if price.unit_price is not None else Decimal("0")
        lines.append(
            ChargeLine(
                charge_category="pharmacy",
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


def aggregate_unbilled_charges(db: Session, visit_id: uuid.UUID, invoice_id: uuid.UUID) -> list[ChargeLine]:
    return (
        _aggregate_lab_charges(db, visit_id, invoice_id)
        + _aggregate_radiology_charges(db, visit_id, invoice_id)
        + _aggregate_pharmacy_charges(db, visit_id, invoice_id)
    )


def _get_invoice_for_visit(db: Session, visit_id: uuid.UUID) -> Invoice:
    invoice = db.execute(
        sa.select(Invoice).where(Invoice.visit_id == visit_id)
    ).scalar_one_or_none()
    if invoice is None:
        # Invoices are created at registration (per schema doc §3 0014),
        # not by this endpoint. A missing invoice means registration
        # didn't run, or PID mismatch — surfacing that is more useful
        # than silently creating one here with no registration line.
        raise NotFoundError(f"No invoice found for visit_id={visit_id}. "
                             "Invoices are created at registration.")
    return invoice


def preview_invoice(db: Session, visit_id: uuid.UUID) -> InvoicePreviewResponse:
    """Read-only. Never writes to invoice_items or invoices."""
    invoice = db.execute(
        sa.select(Invoice).where(Invoice.visit_id == visit_id)
    ).scalar_one_or_none()

    if invoice is None:
        new_lines: list[ChargeLine] = []
        already_billed = 0
        existing_gross = Decimal("0")
        invoice_id = None
        invoice_status = None
    else:
        new_lines = aggregate_unbilled_charges(db, visit_id, invoice.id)
        already_billed = db.execute(
            sa.select(sa.func.count()).select_from(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
        ).scalar_one()
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


def build_invoice(
    db: Session,
    visit_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    dry_run: bool = False,
) -> InvoiceBuildResponse:
    """
    Append unbilled, priced charge lines to the visit's draft invoice
    and recompute totals.

    Guards:
    - Invoice must already exist for the visit (see _get_invoice_for_visit).
    - Invoice must be in 'draft' status. Once it leaves draft,
      trg_invoices_freeze / trg_invoice_items_freeze block exactly this
      kind of write at the DB layer — checking here first just turns a
      raw trigger exception into a clean 409 for the API caller.
    - Unpriced lines (pricing.py returned no tariff) are never written.
      They're reported in the response as lines_skipped_unpriced so
      billing staff can chase down a tariff instead of getting a
      silently wrong total.
    """
    invoice = _get_invoice_for_visit(db, visit_id)

    if invoice.status != "draft":
        raise ConflictError(
            f"Invoice {invoice.invoice_number} is '{invoice.status}', not 'draft' — "
            "new charges can no longer be appended. Corrections require a new invoice."
        )

    charge_lines = aggregate_unbilled_charges(db, visit_id, invoice.id)
    priced_lines = [line for line in charge_lines if line.priced]
    skipped = len(charge_lines) - len(priced_lines)

    if dry_run or not priced_lines:
        added_total = _money(sum((line.amount for line in priced_lines), Decimal("0")))
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
    # adjustment aren't touched by the builder — that's a separate
    # discount/scheme workflow — so this only re-derives net_amount
    # from the (now larger) gross_amount.
    invoice.net_amount = _money(
        invoice.gross_amount - Decimal(invoice.discount_amount) - Decimal(invoice.scheme_adjustment)
    )
    invoice.updated_by = actor_user_id

    db.flush()  # surface trigger/constraint errors before commit

    # NOTE: confirm exact log_audit_event(...) signature with the audit
    # module owner — this call assumes kwargs matching audit_logs
    # columns per schema doc §3 0003.
    from app.audit.service import log_audit_event  # local import avoids a hard top-level dependency cycle
    log_audit_event(
        db,
        user_id=actor_user_id,
        action="invoice_charges_appended",
        resource_type="invoices",
        resource_id=invoice.id,
        patient_id=invoice.patient_id,
        visit_id=invoice.visit_id,
        new_value={
            "lines_added": len(priced_lines),
            "lines_skipped_unpriced": skipped,
            "gross_amount": str(invoice.gross_amount),
            "net_amount": str(invoice.net_amount),
        },
    )

    db.commit()
    db.refresh(invoice)

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
# PM-JAY eligibility — STUB
# ---------------------------------------------------------------------

# Config-driven placeholder, matching the schema doc's rule that
# "government scheme coverage must be configurable (lookup table), not
# hardcoded" (HMIS context doc, billing section). This dict is that
# lookup's stand-in until a real `scheme_eligibility_rules`-style table
# and the ABDM/PM-JAY beneficiary API integration exist — that
# integration is a certification-track item and explicitly not mine to
# build (owned by seniors/managers per project scope).
_PMJAY_STUB_CONFIG = {
    "enabled": True,
    "default_status": "not_determined",
}


def check_pmjay_eligibility(
    db: Session, patient_id: uuid.UUID, visit_id: uuid.UUID
) -> PMJAYEligibilityResponse:
    """
    STUB — does not call ABDM/PM-JAY. Always returns 'not_determined'
    (unless the feature is toggled off, then 'not_eligible' with a
    reason) so the invoice UI can show a "verify PM-JAY manually" nudge
    at billing time without pretending to have real eligibility data.

    Do not wire this into automatic scheme_adjustment calculation on
    invoices — that requires a verified eligibility result, which this
    function cannot produce. It exists so the invoice-preview screen
    has a place to surface a prompt; the actual eligibility decision
    stays a manual front-desk/ABDM step until that integration lands.
    """
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
            "PM-JAY eligibility is not yet verified automatically — "
            "this is a stub pending ABDM/PM-JAY beneficiary API integration. "
            "Front desk should verify the beneficiary card/ABHA manually."
        ),
    )

"""POST /billing/invoices/{invoice_id}/issue — the missing draft -> issued step.

Why this existed as a gap
-------------------------
`build_invoice` creates the invoice with status='draft'. `record_payment`
refuses anything outside ("issued", "partially_paid"). The only two assignments
to `invoice.status` in the whole application live inside record_payment and
create_refund, both of which require the invoice to be payable already.

Nothing bridged the two, so no invoice the application built could ever be paid.

It stayed invisible because tests/integration/test_billing_journey.py defines
`_issue_invoice()`, which opens its own engine and runs
`UPDATE invoices SET status='issued'` in raw SQL. The integration test proved
the journey worked by performing, itself, the one step the product was missing.

Runs against real PostgreSQL (tests/billing/conftest.py), which matters here:
trg_invoices_freeze is a database trigger and does not exist in the ORM-built
SQLite schema the shared fixture uses. test_issuing_engages_the_freeze_trigger
is only meaningful because of that.
"""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError

from app.billing import service
from tests.billing.conftest import seed_draft_invoice

pytestmark = pytest.mark.asyncio


async def _add_line(db, invoice_id: uuid.UUID) -> None:
    """No created_by: invoice_items is `class InvoiceItem(UUIDPk, Base)` — it
    carries neither the Blame nor the Timestamps mixin, and migration 0014
    creates only created_at. The line's author is recorded on the invoice, not
    per charge row."""
    await db.execute(
        sa.text(
            "INSERT INTO invoice_items "
            "(id, invoice_id, charge_category, description, quantity, "
            " unit_price, amount) "
            "VALUES (:id, :invoice_id, 'consultation', 'OPD consultation', 1, "
            " 500.00, 500.00)"
        ),
        {"id": uuid.uuid4(), "invoice_id": invoice_id},
    )


async def _row_version(db, invoice_id: uuid.UUID) -> int:
    return (
        await db.execute(
            sa.text("SELECT row_version FROM invoices WHERE id = :id"),
            {"id": invoice_id},
        )
    ).scalar_one()


async def _status(db, invoice_id: uuid.UUID) -> str:
    return (
        await db.execute(
            sa.text("SELECT status FROM invoices WHERE id = :id"),
            {"id": invoice_id},
        )
    ).scalar_one()


async def test_a_draft_invoice_is_not_payable(db, draft_invoice, user):
    """The defect, stated as a test.

    Draft is the only state build_invoice produces, and it is not payable. If
    this ever stops holding, either draft became payable — check
    _PAYABLE_INVOICE_STATUSES, and note that payment against a still-editable
    invoice defeats the freeze trigger — or build stopped producing drafts.
    """
    assert await _status(db, draft_invoice) == "draft"
    assert "draft" not in service._PAYABLE_INVOICE_STATUSES


async def test_issuing_makes_a_draft_payable(db, draft_invoice, user):
    await _add_line(db, draft_invoice)

    issued = await service.issue_invoice(
        db, invoice_id=draft_invoice, updated_by=user,
        expected_row_version=await _row_version(db, draft_invoice),
    )

    assert issued.status == "issued"
    assert issued.status in service._PAYABLE_INVOICE_STATUSES
    assert await _row_version(db, draft_invoice) == 2, "row_version must advance"


async def test_issuing_engages_the_freeze_trigger(db, draft_invoice, user):
    """The point of issuing: trg_invoices_freeze blocks edits to everything but
    status once the invoice leaves draft. Only observable against PostgreSQL —
    the trigger is created by migration 0014 and does not exist in the ORM-built
    SQLite schema, so this assertion is invisible to the default suite.
    """
    await _add_line(db, draft_invoice)
    await service.issue_invoice(
        db, invoice_id=draft_invoice, updated_by=user,
        expected_row_version=await _row_version(db, draft_invoice),
    )

    # net_amount is in the trigger's frozen column set; status and row_version
    # deliberately are not, which is how a payment can still move the invoice
    # issued -> partially_paid -> paid without unfreezing the amounts.
    with pytest.raises(DBAPIError) as caught:
        await db.execute(
            sa.text("UPDATE invoices SET net_amount = 9999 WHERE id = :id"),
            {"id": draft_invoice},
        )

    assert "cannot change frozen columns" in str(caught.value), (
        f"expected trg_invoices_freeze to refuse the amount edit, got: {caught.value}"
    )


async def test_an_invoice_can_only_be_issued_once(db, draft_invoice, user):
    """Corrections are cancel-and-reissue, never an edit, so a second issue is a
    mistake worth surfacing rather than absorbing."""
    await _add_line(db, draft_invoice)
    version = await _row_version(db, draft_invoice)
    await service.issue_invoice(
        db, invoice_id=draft_invoice, updated_by=user, expected_row_version=version,
    )

    with pytest.raises(HTTPException) as caught:
        await service.issue_invoice(
            db, invoice_id=draft_invoice, updated_by=user,
            expected_row_version=await _row_version(db, draft_invoice),
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "invoice_not_draft"


async def test_a_stale_row_version_is_refused(db, draft_invoice, user):
    """The race row_version was added for: departments append charge lines to a
    draft as work completes, so a clerk who loaded the invoice before radiology
    posted its charge would otherwise freeze an invoice missing that line —
    unbillable revenue, and not amendable afterwards."""
    await _add_line(db, draft_invoice)
    stale = await _row_version(db, draft_invoice) - 1

    with pytest.raises(HTTPException) as caught:
        await service.issue_invoice(
            db, invoice_id=draft_invoice, updated_by=user, expected_row_version=stale,
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "stale_write"
    assert await _status(db, draft_invoice) == "draft", "a refused issue must not land"


async def test_an_invoice_with_no_charge_lines_cannot_be_issued(db, draft_invoice, user):
    """Freezing a zero-line invoice is not recoverable by editing, and it can
    never be meaningfully paid."""
    with pytest.raises(HTTPException) as caught:
        await service.issue_invoice(
            db, invoice_id=draft_invoice, updated_by=user,
            expected_row_version=await _row_version(db, draft_invoice),
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "invoice_has_no_items"


async def test_issuing_is_scoped_to_one_facility(db, facility, other_facility, user):
    """The router asserts facility before calling the service; this covers the
    seam directly so the two cannot drift apart."""
    from tests.billing.conftest import seed_patient, seed_user, seed_visit

    their_user = await seed_user(db, facility_id=other_facility)
    their_patient = await seed_patient(db, facility_id=other_facility)
    their_visit = await seed_visit(
        db, facility_id=other_facility, patient_id=their_patient,
    )
    their_invoice = await seed_draft_invoice(
        db, facility_id=other_facility, patient_id=their_patient,
        visit_id=their_visit, created_by=their_user,
    )

    from app.billing.router import _assert_invoice_in_facility

    with pytest.raises(HTTPException) as caught:
        await _assert_invoice_in_facility(db, their_invoice, facility)

    assert caught.value.status_code == 404


async def test_invoice_detail_reports_lines_and_a_zero_payment_balance(db, draft_invoice, user):
    """GET /billing/invoices/{id} replaces three mocks that had no backend:
    getInvoice, listPayments and getInvoiceBalance."""
    from app.billing.router import get_invoice

    await _add_line(db, draft_invoice)

    class _Caller:
        def __init__(self, facility_id):
            self.facility_id = facility_id
            self.id = user
            self.roles = ["receptionist"]

    facility_id = (
        await db.execute(
            sa.text("SELECT facility_id FROM invoices WHERE id = :id"),
            {"id": draft_invoice},
        )
    ).scalar_one()

    detail = await get_invoice(draft_invoice, _Caller(facility_id), db=db)

    assert len(detail.lines) == 1
    assert detail.lines[0].description == "OPD consultation"
    assert detail.payments == []
    assert detail.total_paid == 0
    assert detail.total_refunded == 0
    assert detail.balance_due == detail.net_amount, (
        "with nothing collected, the balance is the whole invoice"
    )


async def test_invoice_detail_is_facility_scoped(db, facility, other_facility, user):
    from app.billing.router import get_invoice
    from tests.billing.conftest import seed_patient, seed_user, seed_visit

    their_user = await seed_user(db, facility_id=other_facility)
    their_patient = await seed_patient(db, facility_id=other_facility)
    their_visit = await seed_visit(
        db, facility_id=other_facility, patient_id=their_patient,
    )
    their_invoice = await seed_draft_invoice(
        db, facility_id=other_facility, patient_id=their_patient,
        visit_id=their_visit, created_by=their_user,
    )

    class _Caller:
        facility_id = facility
        id = user
        roles = ["receptionist"]

    with pytest.raises(HTTPException) as caught:
        await get_invoice(their_invoice, _Caller(), db=db)

    assert caught.value.status_code == 404


async def test_a_missing_invoice_is_404(db, user):
    with pytest.raises(HTTPException) as caught:
        await service.issue_invoice(
            db, invoice_id=uuid.uuid4(), updated_by=user, expected_row_version=1,
        )

    assert caught.value.status_code == 404


@pytest.mark.parametrize(("priced", "code"), [(False, "invoice_has_unpriced_charges"), (True, "invoice_has_unbilled_charges")])
async def test_an_invoice_with_charges_still_off_it_cannot_be_issued(db, draft_invoice, user, monkeypatch, priced, code):
    """QA 12 Oct 2026: issued for Rs 50 with the CBC and X-ray unpriced and unbilled.

    Issuing freezes the invoice, so a charge left off at that moment can never
    be billed. The aggregator is stubbed to the reported shape; the guard is
    what is under test.
    """
    from decimal import Decimal

    from app.billing.schemas import ChargeCategory, ChargeLine

    await _add_line(db, draft_invoice)
    line = ChargeLine(charge_category=ChargeCategory.LAB, reference_type="lab_order_items",
                      reference_id=uuid.uuid4(), description="CBC", unit_price=Decimal("0") if not priced else Decimal("250"),
                      amount=Decimal("0") if not priced else Decimal("250"), priced=priced)

    async def pending(_db, _visit_id, _invoice_id):
        return [line]

    monkeypatch.setattr(service, "aggregate_unbilled_charges", pending)
    with pytest.raises(HTTPException) as caught:
        await service.issue_invoice(db, invoice_id=draft_invoice, updated_by=user,
                                    expected_row_version=await _row_version(db, draft_invoice))
    assert caught.value.detail["code"] == code
    assert "CBC" in caught.value.detail["message"]
    assert await _status(db, draft_invoice) == "draft"

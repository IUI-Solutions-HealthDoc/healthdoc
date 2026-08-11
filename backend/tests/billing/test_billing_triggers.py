"""
DB trigger tests for migration 0014 (trg_invoices_freeze,
trg_invoice_items_freeze, trg_payments_block, trg_refunds_block).

These are the trigger tests the PR description claims were run before
merge ("Tested: trigger tests (blocked UPDATE/DELETE on
payments/refunds, conditional freeze on invoices)") — this file is
where that claim becomes an actual, repeatable assertion instead of a
one-off manual check. Also covers the reviewer's confirmed reading of
"the parent's trigger" for invoice_items (a second, real trigger).

Every test here talks to Postgres directly via db.execute(sa.text(...))
for the UPDATE/DELETE under test — not the ORM — so we're testing the
DB constraint itself, independent of whether app code would ever
attempt that mutation. That's the point: the trigger is the backstop
that holds even if application code has a bug.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from tests.billing.conftest import seed_draft_invoice, seed_user

pytestmark = pytest.mark.asyncio


async def _insert_invoice_item(db, *, invoice_id: uuid.UUID) -> uuid.UUID:
    item_id = uuid.uuid4()
    await db.execute(
        sa.text(
            "INSERT INTO invoice_items "
            "(id, invoice_id, charge_category, description, quantity, unit_price, amount) "
            "VALUES (:id, :invoice_id, 'lab', 'CBC', 1, 300.00, 300.00)"
        ),
        {"id": item_id, "invoice_id": invoice_id},
    )
    return item_id


async def _insert_payment(db, *, invoice_id: uuid.UUID, collected_by: uuid.UUID) -> uuid.UUID:
    payment_id = uuid.uuid4()
    await db.execute(
        sa.text(
            "INSERT INTO payments "
            "(id, receipt_number, invoice_id, amount, mode, collected_by, collected_at, created_by) "
            "VALUES (:id, :num, :invoice_id, 500.00, 'cash', :collected_by, now(), :collected_by)"
        ),
        {"id": payment_id, "num": f"RCP-TST-{str(payment_id)[:8].upper()}", "invoice_id": invoice_id, "collected_by": collected_by},
    )
    return payment_id


async def _insert_refund(db, *, payment_id: uuid.UUID, approved_by: uuid.UUID) -> uuid.UUID:
    refund_id = uuid.uuid4()
    await db.execute(
        sa.text(
            "INSERT INTO refunds "
            "(id, refund_number, payment_id, amount, reason, approved_by, refunded_at, created_by) "
            "VALUES (:id, :num, :payment_id, 100.00, 'test refund', :approved_by, now(), :approved_by)"
        ),
        {"id": refund_id, "num": f"RFD-TST-{str(refund_id)[:8].upper()}", "payment_id": payment_id, "approved_by": approved_by},
    )
    return refund_id


# ---------------------------------------------------------------------
# trg_invoices_freeze — conditional: mutable while draft, status still
# mutable after leaving draft, everything else frozen.
# ---------------------------------------------------------------------


class TestInvoicesFreeze:
    async def test_amounts_are_mutable_while_draft(self, db, draft_invoice):
        await db.execute(
            sa.text("UPDATE invoices SET gross_amount = 500.00, net_amount = 500.00 WHERE id = :id"),
            {"id": draft_invoice},
        )
        row = (await db.execute(sa.text("SELECT net_amount FROM invoices WHERE id = :id"), {"id": draft_invoice})).one()
        assert Decimal(row.net_amount) == Decimal("500.00")

    async def test_amount_change_blocked_once_issued(self, db, draft_invoice):
        await db.execute(sa.text("UPDATE invoices SET status = 'issued' WHERE id = :id"), {"id": draft_invoice})
        with pytest.raises(DBAPIError, match="cannot change frozen columns"):
            await db.execute(
                sa.text("UPDATE invoices SET gross_amount = 999.00 WHERE id = :id"),
                {"id": draft_invoice},
            )

    async def test_status_remains_mutable_once_issued(self, db, draft_invoice):
        """The one exception the trigger explicitly carves out — a payment
        must still be able to move issued -> partially_paid -> paid."""
        await db.execute(sa.text("UPDATE invoices SET status = 'issued' WHERE id = :id"), {"id": draft_invoice})
        await db.execute(
            sa.text("UPDATE invoices SET status = 'partially_paid' WHERE id = :id"),
            {"id": draft_invoice},
        )
        row = (await db.execute(sa.text("SELECT status FROM invoices WHERE id = :id"), {"id": draft_invoice})).one()
        assert row.status == "partially_paid"


# ---------------------------------------------------------------------
# trg_invoice_items_freeze — second trigger, keyed off the PARENT
# invoice's status (invoice_items has no status column of its own).
# ---------------------------------------------------------------------


class TestInvoiceItemsFreeze:
    async def test_editable_while_parent_is_draft(self, db, draft_invoice):
        item_id = await _insert_invoice_item(db, invoice_id=draft_invoice)
        await db.execute(
            sa.text("UPDATE invoice_items SET amount = 350.00 WHERE id = :id"), {"id": item_id}
        )
        row = (await db.execute(sa.text("SELECT amount FROM invoice_items WHERE id = :id"), {"id": item_id})).one()
        assert Decimal(row.amount) == Decimal("350.00")

    async def test_update_blocked_once_parent_leaves_draft(self, db, draft_invoice):
        item_id = await _insert_invoice_item(db, invoice_id=draft_invoice)
        await db.execute(sa.text("UPDATE invoices SET status = 'issued' WHERE id = :id"), {"id": draft_invoice})
        with pytest.raises(DBAPIError, match="parent invoice leaves draft status"):
            await db.execute(
                sa.text("UPDATE invoice_items SET amount = 1.00 WHERE id = :id"), {"id": item_id}
            )

    async def test_delete_blocked_once_parent_leaves_draft(self, db, draft_invoice):
        item_id = await _insert_invoice_item(db, invoice_id=draft_invoice)
        await db.execute(sa.text("UPDATE invoices SET status = 'issued' WHERE id = :id"), {"id": draft_invoice})
        with pytest.raises(DBAPIError, match="parent invoice leaves draft status"):
            await db.execute(sa.text("DELETE FROM invoice_items WHERE id = :id"), {"id": item_id})


# ---------------------------------------------------------------------
# trg_payments_block / trg_refunds_block — UNCONDITIONAL. No draft-like
# exception anywhere; every UPDATE or DELETE raises, always.
# ---------------------------------------------------------------------


class TestPaymentsImmutable:
    async def test_update_blocked(self, db, draft_invoice, user):
        payment_id = await _insert_payment(db, invoice_id=draft_invoice, collected_by=user)
        with pytest.raises(DBAPIError, match="payments: rows are immutable after insert"):
            await db.execute(sa.text("UPDATE payments SET amount = 1.00 WHERE id = :id"), {"id": payment_id})

    async def test_delete_blocked(self, db, draft_invoice, user):
        payment_id = await _insert_payment(db, invoice_id=draft_invoice, collected_by=user)
        with pytest.raises(DBAPIError, match="payments: rows are immutable after insert"):
            await db.execute(sa.text("DELETE FROM payments WHERE id = :id"), {"id": payment_id})


class TestRefundsImmutable:
    async def test_update_blocked(self, db, draft_invoice, user):
        payment_id = await _insert_payment(db, invoice_id=draft_invoice, collected_by=user)
        refund_id = await _insert_refund(db, payment_id=payment_id, approved_by=user)
        with pytest.raises(DBAPIError, match="refunds: rows are immutable after insert"):
            await db.execute(sa.text("UPDATE refunds SET amount = 1.00 WHERE id = :id"), {"id": refund_id})

    async def test_delete_blocked(self, db, draft_invoice, user):
        payment_id = await _insert_payment(db, invoice_id=draft_invoice, collected_by=user)
        refund_id = await _insert_refund(db, payment_id=payment_id, approved_by=user)
        with pytest.raises(DBAPIError, match="refunds: rows are immutable after insert"):
            await db.execute(sa.text("DELETE FROM refunds WHERE id = :id"), {"id": refund_id})


# ---------------------------------------------------------------------
# CHECK constraints — regression test for the enum-based swap
# (ChargeCategory/PaymentMode/PaymentStatus.sql_check()).
# ---------------------------------------------------------------------


class TestCheckConstraints:
    async def test_invalid_charge_category_rejected(self, db, draft_invoice):
        with pytest.raises(DBAPIError, match="ck_invoice_items_charge_category"):
            await db.execute(
                sa.text(
                    "INSERT INTO invoice_items "
                    "(id, invoice_id, charge_category, description, quantity, unit_price, amount) "
                    "VALUES (:id, :invoice_id, 'not_a_real_category', 'x', 1, 1.00, 1.00)"
                ),
                {"id": uuid.uuid4(), "invoice_id": draft_invoice},
            )

    async def test_invalid_payment_mode_rejected(self, db, draft_invoice, user):
        with pytest.raises(DBAPIError, match="ck_payments_mode"):
            await db.execute(
                sa.text(
                    "INSERT INTO payments "
                    "(id, receipt_number, invoice_id, amount, mode, collected_by, collected_at, created_by) "
                    "VALUES (:id, :num, :invoice_id, 100.00, 'bitcoin', :user, now(), :user)"
                ),
                {"id": uuid.uuid4(), "num": "RCP-BAD-00001", "invoice_id": draft_invoice, "user": user},
            )

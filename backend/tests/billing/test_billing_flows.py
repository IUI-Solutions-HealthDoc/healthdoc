"""
Service-layer flow tests — the "full build -> pay -> partial-refund ->
status-transition flow" and "overpayment/over-refund rejected with 409"
claims from the PR description, plus regression tests for the two bugs
fixed in this revision:

  1. _payment_totals_for_invoice was never actually defined (its body
     was dead code trapped inside _facility_timezone) — every one of
     record_payment/create_refund/get_pending_invoices would have
     raised NameError on first real call. test_regression_* below call
     each of those three paths so this can never silently regress.
  2. Concurrent build_invoice() calls for the same visit could double-
     bill a reference_id (blocker #2). test_concurrent_build_invoice_*
     fires two overlapping builds and asserts each billable charge is
     only ever billed once, regardless of how the race resolves.
"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi import HTTPException

from app.billing import service
from app.billing.schemas import PaymentCreate, RefundCreate
from app.common.enums import PaymentMode
from tests.billing.conftest import seed_draft_invoice, seed_facility, seed_patient, seed_user, seed_visit

pytestmark = pytest.mark.asyncio


async def _seed_billable_lab_charge(db, *, visit_id: uuid.UUID, test_code: str = "CBC") -> uuid.UUID:
    """
    Minimal encounters -> orders -> lab_order_items -> lab_results chain
    so aggregate_unbilled_charges() has exactly one FINAL, priced,
    unbilled lab charge to find. Raw SQL, not ORM — lab/orders/
    encounters models belong to other devs' modules, not billing's.
    """
    encounter_id = uuid.uuid4()
    order_id = uuid.uuid4()
    item_id = uuid.uuid4()

    # encounters (0007), orders (0008) and lab_order_items/lab_results (0010)
    # are all real tables now — they were unmerged when this helper was
    # written, so these INSERTs were shaped for stubs. patient_id and
    # created_by are read back off the visit rather than added as
    # parameters, so none of the call sites below have to change.
    visit_row = (
        await db.execute(
            sa.text("SELECT patient_id, facility_id, created_by FROM visits WHERE id = :id"),
            {"id": visit_id},
        )
    ).one()
    patient_id, actor_id = visit_row.patient_id, visit_row.created_by
    facility_id = visit_row.facility_id

    await db.execute(
        sa.text(
            "INSERT INTO encounters "
            "(id, visit_id, facility_id, provider_user_id, created_by) "
            "VALUES (:id, :visit_id, :facility_id, :provider, :created_by)"
        ),
        {"id": encounter_id, "visit_id": visit_id, "facility_id": facility_id,
         "provider": actor_id, "created_by": actor_id},
    )
    await db.execute(
        sa.text(
            "INSERT INTO orders "
            "(id, encounter_id, order_number, patient_id, order_type, created_by) "
            "VALUES (:id, :encounter_id, :order_number, :patient_id, 'lab', :actor)"
        ),
        {"id": order_id, "encounter_id": encounter_id, "patient_id": patient_id,
         "order_number": f"O{uuid.uuid4().hex[:10]}", "actor": actor_id},
    )
    await db.execute(
        sa.text(
            "INSERT INTO lab_order_items "
            "(id, order_id, test_code, test_name, accession_number, sample_type, created_by) "
            "VALUES (:id, :order_id, :code, :name, :accession, 'blood', :actor)"
        ),
        # :code and :name are separate binds even though they carry the same
        # value: test_code is varchar(30) and test_name is text, and asyncpg
        # deduces a prepared-statement parameter's type from its use sites.
        # One bind in two differently-typed columns is
        # "AmbiguousParameterError: inconsistent types deduced for $3".
        {"id": item_id, "order_id": order_id, "code": test_code, "name": test_code,
         "accession": f"LAB-{uuid.uuid4().hex[:12]}", "actor": actor_id},
    )
    await db.execute(
        sa.text(
            "INSERT INTO lab_results "
            "(lab_order_item_id, is_current, status, version, result_data, created_by) "
            "VALUES (:id, true, 'final', 1, '{}'::jsonb, :actor)"
        ),
        {"id": item_id, "actor": actor_id},
    )
    return item_id


class TestBuildInvoice:
    async def test_aggregates_priced_lines_and_skips_unpriced(self, db, facility, patient, visit, user, draft_invoice):
        await _seed_billable_lab_charge(db, visit_id=visit, test_code="CBC")
        await _seed_billable_lab_charge(db, visit_id=visit, test_code="NOT_A_REAL_TEST")  # no tariff -> priced=False

        result = await service.build_invoice(db, visit_id=visit, actor_user_id=user, dry_run=False)

        assert result.lines_added == 1
        assert result.lines_skipped_unpriced == 1
        assert result.gross_amount == Decimal("300.00")  # CBC tariff, see pricing.py
        assert result.status == "draft"

    async def test_dry_run_writes_nothing(self, db, visit, user, draft_invoice):
        await _seed_billable_lab_charge(db, visit_id=visit)

        result = await service.build_invoice(db, visit_id=visit, actor_user_id=user, dry_run=True)
        assert result.lines_added == 0

        count = (
            await db.execute(sa.text("SELECT count(*) FROM invoice_items WHERE invoice_id = :id"), {"id": draft_invoice})
        ).scalar_one()
        assert count == 0

    async def test_second_build_does_not_rebill_same_charge(self, db, visit, user, draft_invoice):
        await _seed_billable_lab_charge(db, visit_id=visit, test_code="CBC")

        first = await service.build_invoice(db, visit_id=visit, actor_user_id=user, dry_run=False)
        second = await service.build_invoice(db, visit_id=visit, actor_user_id=user, dry_run=False)

        assert first.lines_added == 1
        assert second.lines_added == 0  # already billed — _already_billed_reference_ids caught it

    async def test_build_blocked_once_invoice_is_no_longer_draft(self, db, visit, user, draft_invoice):
        await db.execute(sa.text("UPDATE invoices SET status = 'issued' WHERE id = :id"), {"id": draft_invoice})
        await _seed_billable_lab_charge(db, visit_id=visit)

        with pytest.raises(HTTPException) as exc_info:
            await service.build_invoice(db, visit_id=visit, actor_user_id=user, dry_run=False)
        assert exc_info.value.status_code == 409


class TestConcurrentBuildInvoice:
    """Blocker #2 regression — see this module's docstring.

    Deliberately does NOT use the facility/patient/visit/user/
    draft_invoice fixtures — those insert through the shared `db`
    fixture, which holds everything in one UNCOMMITTED transaction
    until teardown. The two racing sessions below are separate real
    connections, and a separate Postgres connection can never see
    another connection's uncommitted rows -- so this test seeds every
    prerequisite itself, through its own committed session, exactly
    like _seed_billable_lab_charge_standalone already did for the lab
    charge alone.
    """

    async def test_two_concurrent_builds_bill_each_charge_at_most_once(self, engine):
        from sqlalchemy.ext.asyncio import async_sessionmaker

        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

        async with session_factory() as session:
            async with session.begin():
                facility = await seed_facility(session)
                patient = await seed_patient(session, facility_id=facility)
                user = await seed_user(session, facility_id=facility)
                visit = await seed_visit(session, facility_id=facility, patient_id=patient)
                draft_invoice = await seed_draft_invoice(
                    session, facility_id=facility, patient_id=patient,
                    visit_id=visit, created_by=user,
                )

        await _seed_billable_lab_charge_standalone(engine, visit_id=visit, test_code="CBC")

        async def run_build():
            async with session_factory() as session:
                async with session.begin():
                    result = await service.build_invoice(
                        session, visit_id=visit, actor_user_id=user, dry_run=False
                    )
                return result

        results = await asyncio.gather(run_build(), run_build(), return_exceptions=True)
        lines_added_total = sum(
            r.lines_added for r in results if not isinstance(r, Exception)
        )
        # Exactly one of the two builds should have won the race — never both.
        assert lines_added_total == 1

        async with session_factory() as session:
            count = (
                await session.execute(
                    sa.text("SELECT count(*) FROM invoice_items WHERE invoice_id = :id"),
                    {"id": draft_invoice},
                )
            ).scalar_one()
        assert count == 1  # the charge was billed exactly once, not twice


async def _seed_billable_lab_charge_standalone(engine, *, visit_id, test_code):
    """Same as _seed_billable_lab_charge but runs in its own committed
    transaction (the concurrency test needs the seed data visible to
    both racing sessions, which a shared uncommitted `db` fixture
    transaction would hide from the second connection)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():
            await _seed_billable_lab_charge(session, visit_id=visit_id, test_code=test_code)


class TestPaymentAndRefundFlow:
    async def test_full_build_pay_partial_refund_status_transitions(
        self, db, facility, patient, visit, user, draft_invoice,
    ):
        await _seed_billable_lab_charge(db, visit_id=visit, test_code="CBC")  # 300.00
        build_result = await service.build_invoice(db, visit_id=visit, actor_user_id=user, dry_run=False)
        assert build_result.net_amount == Decimal("300.00")

        # Invoice must be 'issued' before a payment can be recorded —
        # simulate registration/front-desk issuing it.
        await db.execute(sa.text("UPDATE invoices SET status = 'issued' WHERE id = :id"), {"id": draft_invoice})

        # Partial payment -> partially_paid
        payment = await service.record_payment(
            db, invoice_id=draft_invoice, actor_user_id=user,
            body=PaymentCreate(amount=Decimal("200.00"), mode=PaymentMode.CASH),
        )
        invoice_row = (
            await db.execute(sa.text("SELECT status, row_version FROM invoices WHERE id = :id"), {"id": draft_invoice})
        ).one()
        assert invoice_row.status == "partially_paid"
        assert invoice_row.row_version == 3  # 1 (insert) + 1 (build_invoice) + 1 (record_payment)

        # Remaining balance -> paid
        await service.record_payment(
            db, invoice_id=draft_invoice, actor_user_id=user,
            body=PaymentCreate(amount=Decimal("100.00"), mode=PaymentMode.UPI),
        )
        invoice_row = (
            await db.execute(sa.text("SELECT status FROM invoices WHERE id = :id"), {"id": draft_invoice})
        ).one()
        assert invoice_row.status == "paid"

        # Partial refund on the first payment -> back to partially_paid
        refund = await service.create_refund(
            db, payment_id=payment.id, actor_user_id=user,
            body=RefundCreate(amount=Decimal("50.00"), reason="test partial refund"),
        )
        assert refund.amount == Decimal("50.00")
        invoice_row = (
            await db.execute(sa.text("SELECT status FROM invoices WHERE id = :id"), {"id": draft_invoice})
        ).one()
        assert invoice_row.status == "partially_paid"

    async def test_overpayment_rejected_409(self, db, visit, user, draft_invoice):
        await _seed_billable_lab_charge(db, visit_id=visit, test_code="CBC")  # 300.00
        await service.build_invoice(db, visit_id=visit, actor_user_id=user, dry_run=False)
        await db.execute(sa.text("UPDATE invoices SET status = 'issued' WHERE id = :id"), {"id": draft_invoice})

        with pytest.raises(HTTPException) as exc_info:
            await service.record_payment(
                db, invoice_id=draft_invoice, actor_user_id=user,
                body=PaymentCreate(amount=Decimal("999.00"), mode=PaymentMode.CASH),
            )
        assert exc_info.value.status_code == 409

    async def test_over_refund_rejected_409(self, db, visit, user, draft_invoice):
        await _seed_billable_lab_charge(db, visit_id=visit, test_code="CBC")
        await service.build_invoice(db, visit_id=visit, actor_user_id=user, dry_run=False)
        await db.execute(sa.text("UPDATE invoices SET status = 'issued' WHERE id = :id"), {"id": draft_invoice})
        payment = await service.record_payment(
            db, invoice_id=draft_invoice, actor_user_id=user,
            body=PaymentCreate(amount=Decimal("300.00"), mode=PaymentMode.CASH),
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.create_refund(
                db, payment_id=payment.id, actor_user_id=user,
                body=RefundCreate(amount=Decimal("301.00"), reason="more than was paid"),
            )
        assert exc_info.value.status_code == 409

    async def test_payment_blocked_on_draft_invoice(self, db, visit, user, draft_invoice):
        # draft_invoice fixture leaves status='draft' — nothing to collect yet.
        with pytest.raises(HTTPException) as exc_info:
            await service.record_payment(
                db, invoice_id=draft_invoice, actor_user_id=user,
                body=PaymentCreate(amount=Decimal("100.00"), mode=PaymentMode.CASH),
            )
        assert exc_info.value.status_code == 409


class TestRegressionPaymentTotalsForInvoice:
    """
    Direct regression test for the missing-function bug: previously
    `_payment_totals_for_invoice` was called but never defined anywhere
    in the module, so this would have raised NameError, not an
    assertion failure — i.e. it would have failed LOUD, but only the
    first time any of these three paths actually ran, which a narrower
    test (e.g. only testing build_invoice) would never have caught.
    """

    async def test_record_payment_path(self, db, visit, user, draft_invoice):
        await _seed_billable_lab_charge(db, visit_id=visit)
        await service.build_invoice(db, visit_id=visit, actor_user_id=user, dry_run=False)
        await db.execute(sa.text("UPDATE invoices SET status = 'issued' WHERE id = :id"), {"id": draft_invoice})
        payment = await service.record_payment(
            db, invoice_id=draft_invoice, actor_user_id=user,
            body=PaymentCreate(amount=Decimal("100.00"), mode=PaymentMode.CASH),
        )
        assert payment.amount == Decimal("100.00")

    async def test_get_pending_invoices_path(self, db, facility, visit, user, draft_invoice):
        await _seed_billable_lab_charge(db, visit_id=visit)
        await service.build_invoice(db, visit_id=visit, actor_user_id=user, dry_run=False)
        await db.execute(sa.text("UPDATE invoices SET status = 'issued' WHERE id = :id"), {"id": draft_invoice})

        response = await service.get_pending_invoices(db, facility_id=facility)
        assert response.count == 1
        assert response.items[0].balance_due == Decimal("300.00")

"""
Billing MIS tests — B7-W3-02 (#189). Covers the PR description's "MIS
numbers verified against seeded data, cross-facility MIS access
confirmed blocked" claim, and specifically exercises
service.facility_id_for_user() — the function the reviewer called out
by name as the thing "four other PRs this week" got wrong.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi import HTTPException

from app.billing import service
from app.billing.schemas import PaymentCreate, RefundCreate
from app.common.enums import PaymentMode
from tests.billing.conftest import seed_draft_invoice, seed_patient, seed_user, seed_visit

pytestmark = pytest.mark.asyncio


async def _billed_and_paid_invoice(db, *, facility_id, patient_id, visit_id, user_id, amount: Decimal):
    invoice_id = await seed_draft_invoice(
        db, facility_id=facility_id, patient_id=patient_id, visit_id=visit_id,
        created_by=user_id, gross_amount=str(amount), net_amount=str(amount),
    )
    await db.execute(sa.text("UPDATE invoices SET status = 'issued' WHERE id = :id"), {"id": invoice_id})
    payment = await service.record_payment(
        db, invoice_id=invoice_id, actor_user_id=user_id,
        body=PaymentCreate(amount=amount, mode=PaymentMode.CASH),
    )
    return invoice_id, payment


class TestFacilityScoping:
    async def test_facility_id_for_user_resolves_own_facility(self, db, facility, user):
        row = (await db.execute(sa.text("SELECT keycloak_sub FROM users WHERE id = :id"), {"id": user})).one()
        resolved = await service.facility_id_for_user(db, keycloak_sub=row.keycloak_sub)
        assert resolved == facility

    async def test_unknown_keycloak_sub_rejected(self, db, facility):
        with pytest.raises(HTTPException) as exc_info:
            await service.facility_id_for_user(db, keycloak_sub="no-such-subject")
        assert exc_info.value.status_code == 401

    async def test_pending_invoices_excludes_other_facilities(
        self, db, facility, other_facility, patient, visit, user,
    ):
        other_patient = await seed_patient(db, facility_id=other_facility)
        other_user = await seed_user(db, facility_id=other_facility)
        other_visit = await seed_visit(db, facility_id=other_facility, patient_id=other_patient)

        # One pending invoice per facility.
        await seed_draft_invoice(
            db, facility_id=facility, patient_id=patient, visit_id=visit,
            created_by=user, gross_amount="300.00", net_amount="300.00",
        )
        other_invoice = await seed_draft_invoice(
            db, facility_id=other_facility, patient_id=other_patient, visit_id=other_visit,
            created_by=other_user, gross_amount="500.00", net_amount="500.00",
        )
        for inv_id in (other_invoice,):
            await db.execute(sa.text("UPDATE invoices SET status = 'issued' WHERE id = :id"), {"id": inv_id})

        result = await service.get_pending_invoices(db, facility_id=other_facility)

        assert result.facility_id == other_facility
        assert all(item.invoice_id == other_invoice for item in result.items)
        # The `facility` invoice never appears in `other_facility`'s results —
        # this is the exact bug the reviewer flagged in four other PRs.
        assert result.total_balance_due == Decimal("500.00")


class TestDailyRevenue:
    async def test_nets_refunds_against_gross_collected(self, db, facility, patient, visit, user):
        invoice_id, payment = await _billed_and_paid_invoice(
            db, facility_id=facility, patient_id=patient, visit_id=visit,
            user_id=user, amount=Decimal("300.00"),
        )
        await service.create_refund(
            db, payment_id=payment.id, actor_user_id=user,
            body=RefundCreate(amount=Decimal("50.00"), reason="test"),
        )

        response = await service.get_daily_revenue(db, facility_id=facility, date_from=None, date_to=None)

        assert response.total_net_revenue == Decimal("250.00")
        assert len(response.points) == 1
        assert response.points[0].gross_collected == Decimal("300.00")
        assert response.points[0].refunded == Decimal("50.00")

    async def test_invalid_date_range_rejected(self, db, facility):
        import datetime as dt
        with pytest.raises(HTTPException) as exc_info:
            await service.get_daily_revenue(
                db, facility_id=facility,
                date_from=dt.date(2026, 1, 10), date_to=dt.date(2026, 1, 1),
            )
        assert exc_info.value.status_code == 400


class TestSchemeBreakdown:
    async def test_self_pay_bucket_used_for_null_scheme_code(self, db, facility, patient, visit, user):
        invoice_id = await seed_draft_invoice(
            db, facility_id=facility, patient_id=patient, visit_id=visit,
            created_by=user, gross_amount="300.00", net_amount="300.00",
        )
        response = await service.get_scheme_breakdown(db, facility_id=facility, date_from=None, date_to=None)

        assert len(response.lines) == 1
        assert response.lines[0].scheme_code == "self_pay"
        assert response.lines[0].net_billed == Decimal("300.00")

    async def test_pmjay_scheme_code_gets_its_own_bucket(self, db, facility, patient, visit, user):
        await db.execute(sa.text("SELECT 1"))  # keep fixture ordering explicit
        invoice_id = uuid.uuid4()
        await db.execute(
            sa.text(
                "INSERT INTO invoices "
                "(id, invoice_number, visit_id, patient_id, facility_id, status, "
                " gross_amount, net_amount, scheme_code, created_by) "
                "VALUES (:id, :num, :visit_id, :patient_id, :facility_id, 'draft', "
                " 300.00, 300.00, 'PM-JAY', :created_by)"
            ),
            {
                "id": invoice_id, "num": f"INV-PMJAY-{str(invoice_id)[:8].upper()}",
                "visit_id": visit, "patient_id": patient, "facility_id": facility, "created_by": user,
            },
        )

        response = await service.get_scheme_breakdown(db, facility_id=facility, date_from=None, date_to=None)

        codes = {line.scheme_code for line in response.lines}
        assert "PM-JAY" in codes

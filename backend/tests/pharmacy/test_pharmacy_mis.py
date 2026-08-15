from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.pharmacy.schemas import DispenseCreate, DispenseItemCreate
from app.pharmacy.service import create_dispense, get_pharmacy_mis_report


@pytest.mark.asyncio
async def test_empty_period_returns_zeroes_not_errors(db_session, pharmacy_seed):
    # pharmacy_seed's prescription is created with created_at=now(), so the
    # queried window must be safely BEFORE today to be genuinely empty --
    # otherwise this is testing "one prescription" and calling it zero.
    report = await get_pharmacy_mis_report(
        db_session,
        facility_id=pharmacy_seed["facility_id"],
        date_from=date.today() - timedelta(days=60),
        date_to=date.today() - timedelta(days=59),
    )
    assert report.prescriptions_total == 0
    assert report.dispenses_total == 0
    assert report.fill_rate_pct == Decimal("0")
    assert report.stockout_count == 0
    assert report.substitution_count == 0
    assert report.substitution_rate_pct == Decimal("0")
    assert report.avg_turnaround_minutes is None


@pytest.mark.asyncio
async def test_default_date_range_resolves_via_facility_timezone(db_session, pharmacy_seed):
    report = await get_pharmacy_mis_report(
        db_session,
        facility_id=pharmacy_seed["facility_id"],
        date_from=None,
        date_to=None,
    )
    # Asia/Kolkata (pharmacy_seed's facility timezone) is fixed within a
    # single calendar day's tolerance of the test host, whatever it is.
    assert report.period_end - report.period_start == timedelta(days=30)


@pytest.mark.asyncio
async def test_date_from_after_date_to_is_422(db_session, pharmacy_seed):
    with pytest.raises(HTTPException) as exc_info:
        await get_pharmacy_mis_report(
            db_session,
            facility_id=pharmacy_seed["facility_id"],
            date_from=date.today(),
            date_to=date.today() - timedelta(days=1),
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_dispensed_prescription_counts_toward_fill_rate(db_session, pharmacy_seed):
    await create_dispense(
        db_session,
        DispenseCreate(
            prescription_id=pharmacy_seed["prescription_id"],
            items=[DispenseItemCreate(
                prescription_item_id=pharmacy_seed["prescription_item_id"],
                quantity_dispensed=Decimal("10"),
            )],
        ),
        current_user_id=pharmacy_seed["pharmacist_id"],
        facility_id=pharmacy_seed["facility_id"],
    )

    report = await get_pharmacy_mis_report(
        db_session,
        facility_id=pharmacy_seed["facility_id"],
        date_from=date.today() - timedelta(days=1),
        date_to=date.today() + timedelta(days=1),
    )
    assert report.prescriptions_total == 1
    assert report.dispenses_total == 1
    assert report.fill_rate_pct == Decimal("100")
    assert report.stockout_count == 0
    assert report.avg_turnaround_minutes is not None
    assert report.avg_turnaround_minutes >= Decimal("0")


@pytest.mark.asyncio
async def test_insufficient_stock_without_partial_counts_as_stockout(db_session, pharmacy_seed):
    # early(6) + late(20) = 26 available; request more than that with no
    # allow_partial so create_dispense rejects it outright (422) rather than
    # ever inserting an out_of_stock row -- confirming stockout_count only
    # reflects dispenses that were actually created, not rejected requests.
    with pytest.raises(HTTPException):
        await create_dispense(
            db_session,
            DispenseCreate(
                prescription_id=pharmacy_seed["prescription_id"],
                items=[DispenseItemCreate(
                    prescription_item_id=pharmacy_seed["prescription_item_id"],
                    quantity_dispensed=Decimal("1000"),
                )],
            ),
            current_user_id=pharmacy_seed["pharmacist_id"],
            facility_id=pharmacy_seed["facility_id"],
        )

    report = await get_pharmacy_mis_report(
        db_session,
        facility_id=pharmacy_seed["facility_id"],
        date_from=date.today() - timedelta(days=1),
        date_to=date.today() + timedelta(days=1),
    )
    assert report.dispenses_total == 0
    assert report.stockout_count == 0


@pytest.mark.asyncio
async def test_substitution_counts_toward_substitution_rate(db_session, pharmacy_seed, monkeypatch):
    import app.pharmacy.service as pharmacy_service

    async def suppress_notification(*args, **kwargs):
        return None

    monkeypatch.setattr(
        pharmacy_service, "_notify_substitution_stakeholders", suppress_notification
    )

    await create_dispense(
        db_session,
        DispenseCreate(
            prescription_id=pharmacy_seed["prescription_id"],
            items=[DispenseItemCreate(
                prescription_item_id=pharmacy_seed["prescription_item_id"],
                quantity_dispensed=Decimal("5"),
                substitute_item_id=pharmacy_seed["medicine_id"],
                substitute_reason="MIS test substitution",
            )],
        ),
        current_user_id=pharmacy_seed["pharmacist_id"],
        facility_id=pharmacy_seed["facility_id"],
    )

    report = await get_pharmacy_mis_report(
        db_session,
        facility_id=pharmacy_seed["facility_id"],
        date_from=date.today() - timedelta(days=1),
        date_to=date.today() + timedelta(days=1),
    )
    assert report.dispenses_total == 1
    assert report.substitution_count == 1
    assert report.substitution_rate_pct == Decimal("100")


@pytest.mark.asyncio
async def test_expiring_batches_respects_window_and_null_price_contributes_zero(
    db_session, pharmacy_seed
):
    # early_batch_id expires in 10 days (qty 6), late_batch_id in 100 days
    # (qty 20); neither has issue_rate_mrp set. Default window is 30 days,
    # so only "early" should be counted, and its NULL price must contribute
    # 0 to expiring_stock_value rather than raising or nulling the total.
    report = await get_pharmacy_mis_report(
        db_session,
        facility_id=pharmacy_seed["facility_id"],
        date_from=date.today() - timedelta(days=1),
        date_to=date.today(),
        expiry_window_days=30,
    )
    assert report.expiring_batches_count == 1
    assert report.expiring_stock_value == Decimal("0")


@pytest.mark.asyncio
async def test_expiring_batches_widened_window_includes_both(db_session, pharmacy_seed):
    report = await get_pharmacy_mis_report(
        db_session,
        facility_id=pharmacy_seed["facility_id"],
        date_from=date.today() - timedelta(days=1),
        date_to=date.today(),
        expiry_window_days=120,
    )
    assert report.expiring_batches_count == 2


@pytest.mark.asyncio
async def test_facility_isolation_other_facility_data_excluded(db_session, pharmacy_seed):
    other_facility_id = uuid.uuid4()
    await db_session.execute(text("""
        INSERT INTO facilities (id, code, name, state_code, timezone)
        VALUES (:id, :code, 'Other Facility', 'TS', 'Asia/Kolkata')
    """), {"id": other_facility_id, "code": f"OTH{uuid.uuid4().hex[:8]}"})
    await db_session.flush()

    report = await get_pharmacy_mis_report(
        db_session,
        facility_id=other_facility_id,
        date_from=date.today() - timedelta(days=1),
        date_to=date.today() + timedelta(days=1),
    )
    assert report.prescriptions_total == 0
    assert report.dispenses_total == 0
    assert report.expiring_batches_count == 0

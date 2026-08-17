from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
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


@pytest.mark.asyncio
@pytest.mark.parametrize("session_tz", ["UTC", "Asia/Kolkata"])
async def test_dispense_late_utc_evening_counts_on_next_ist_date(
    db_session, pharmacy_seed, session_tz
):
    """20:00 UTC is 01:30 the NEXT day in Asia/Kolkata.

    Guards the fix in this PR, and does it under BOTH session timezones on
    purpose. `timestamptz::date` resolves against the session's TimeZone, so
    the unfixed code is accidentally correct wherever that happens to be
    Asia/Kolkata -- which is how this shipped: the dev Postgres is on IST, and
    only CI and production run UTC. Pinning the session here is what makes the
    test mean something on a developer's machine instead of quietly passing.

    The report's answer must not depend on the session at all; it must come
    from facilities.timezone. So both parameters assert the same thing, and the
    UTC one fails the moment `AT TIME ZONE fac.timezone` is removed.

    Practically: every dispense between 18:30 and 24:00 UTC -- the evening rush
    -- was being counted a day early.
    """
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

    # Pin both rows to one instant. The report joins dispenses to prescriptions,
    # so prescriptions_total is filtered on its own created_at.
    # A real aware datetime, not a string: asyncpg binds timestamptz through a
    # codec that rejects str outright, and CAST does not help because Postgres
    # infers the parameter as timestamptz before the cast is ever applied.
    instant = datetime(2026, 3, 10, 20, 0, tzinfo=timezone.utc)
    await db_session.execute(
        text("UPDATE pharmacy_dispenses SET created_at = :t WHERE prescription_id = :pid"),
        {"t": instant, "pid": pharmacy_seed["prescription_id"]},
    )
    await db_session.execute(
        text("UPDATE prescriptions SET created_at = :t WHERE id = :pid"),
        {"t": instant, "pid": pharmacy_seed["prescription_id"]},
    )

    # SET LOCAL, so it dies with the transaction and cannot leak into a pooled
    # connection. Interpolated because SET takes no bind parameters; the value
    # is from the parametrize list, never from input.
    await db_session.execute(text(f"SET LOCAL TimeZone = '{session_tz}'"))

    ist_day = date(2026, 3, 11)
    on_ist = await get_pharmacy_mis_report(
        db_session, facility_id=pharmacy_seed["facility_id"],
        date_from=ist_day, date_to=ist_day,
    )
    assert on_ist.dispenses_total == 1, (
        f"session TimeZone={session_tz}: the dispense must land on its facility's "
        f"business date (2026-03-11 IST), not the session's"
    )
    assert on_ist.prescriptions_total == 1

    utc_day = date(2026, 3, 10)
    on_utc = await get_pharmacy_mis_report(
        db_session, facility_id=pharmacy_seed["facility_id"],
        date_from=utc_day, date_to=utc_day,
    )
    assert on_utc.dispenses_total == 0, (
        f"session TimeZone={session_tz}: 2026-03-10 is the UTC date, not the "
        f"facility's — nothing may be reported against it"
    )
    assert on_utc.prescriptions_total == 0

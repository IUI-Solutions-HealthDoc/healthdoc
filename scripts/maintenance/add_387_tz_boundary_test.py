#!/usr/bin/env python3
"""Add the boundary test that locks in #387's timezone fix. Idempotent.

Run from the repo root on feat/b6-w6-pharmacy-mis.

WHY
---
#387 correctly replaced four `X.created_at::date BETWEEN` with
`(X.created_at AT TIME ZONE fac.timezone)::date BETWEEN`, and shipped nine
tests. None of them fail if the fix is reverted.

That matters more here than usual, because the bug is invisible in two of the
three places you would look for it:

  * `timestamptz::date` resolves using the session's TimeZone GUC. Set the
    session to Asia/Kolkata -- which a developer's local psql often is -- and
    the unfixed code gives the right answer. It only breaks where the session
    is UTC: the CI runner, and production.
  * Any test seeding rows with now() and querying a range around today passes
    either way, because a 5h30m shift rarely crosses a range boundary that
    wide. Eight of the nine tests are that shape.

So the fix is right and the suite would not notice losing it. This adds the
one case that pins it: 20:00 UTC is 01:30 the NEXT day in Asia/Kolkata, so a
dispense at that instant must be reported on the 11th and must not appear on
the 10th. Reverting the fix flips both assertions.

Every dispense between 18:30 and 24:00 UTC is affected -- the last five and a
half hours of every business day, which for a pharmacy is the evening rush.
"""
import pathlib
import sys

ROOT = pathlib.Path(".")
TESTS = ROOT / "backend/tests/pharmacy/test_pharmacy_mis.py"
if not TESTS.exists():
    sys.exit("run me from the repo root, on feat/b6-w6-pharmacy-mis")

text = TESTS.read_text()

MARKER = "test_dispense_late_utc_evening_counts_on_next_ist_date"
if MARKER in text:
    print("~ boundary test already present")
    sys.exit(0)

# The test binds an aware datetime, so the module needs both names.
if "from datetime import date, datetime, timedelta, timezone" not in text:
    text = text.replace(
        "from datetime import date, timedelta",
        "from datetime import date, datetime, timedelta, timezone",
        1,
    )
    print("+ widened the datetime import")

if "AT TIME ZONE" not in (ROOT / "backend/app/pharmacy/service.py").read_text():
    sys.exit("! service.py has no AT TIME ZONE -- wrong branch, or the fix is gone")

TEST = '''

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
'''

TESTS.write_text(text.rstrip("\n") + "\n" + TEST)
print("+ added test_dispense_late_utc_evening_counts_on_next_ist_date")
print("\nverify it actually guards the fix:")
print("  1. cd backend && pytest tests/pharmacy/test_pharmacy_mis.py -k late_utc   # passes")
print("  2. revert AT TIME ZONE in service.py, rerun                              # must FAIL")
print("  3. restore")

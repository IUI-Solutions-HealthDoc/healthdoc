"""Race-safe visit number allocator (schema doc Section 3-0007):
VST-<FACILITYCODE>-<YYYYMMDD>-<SEQ5>.

Same ON CONFLICT ... DO UPDATE ... RETURNING pattern as
app/orders/order_number.py (migration 0019's fix for a COUNT(*) race),
scoped per-facility here since visit_number_counters (migration 0025)
has a (facility_id, counter_date) composite key.

Business date computed in IST (Asia/Kolkata), not UTC, per the schema
doc's blanket rule. facilities.timezone doesn't exist yet (deferred to
v3.5 in the doc's backlog) -- every current deployment is India-only,
so IST is hardcoded here as the documented interim approach.
"""
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

IST = ZoneInfo("Asia/Kolkata")


async def next_visit_sequence(db: AsyncSession, facility_id: UUID) -> int:
    business_date = datetime.now(IST).date()

    result = await db.execute(
        text(
            "INSERT INTO visit_number_counters (facility_id, counter_date, seq) "
            "VALUES (:facility_id, :d, 1) "
            "ON CONFLICT (facility_id, counter_date) DO UPDATE "
            "SET seq = visit_number_counters.seq + 1 "
            "RETURNING seq"
        ),
        {"facility_id": facility_id, "d": business_date},
    )
    return result.scalar_one()

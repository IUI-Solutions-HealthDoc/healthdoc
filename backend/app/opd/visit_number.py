"""
backend/app/opd/visit_number.py

Race-safe visit number allocator (schema doc §3-0007):
VST-<FACILITYCODE>-<YYYYMMDD>-<SEQ5>.

Uses INSERT ... ON CONFLICT (facility_id, counter_date) DO UPDATE ...
RETURNING seq -- a single atomic statement, race-safe without a
separate SELECT ... FOR UPDATE round trip. (Note: the previous
docstring here cited this as mirroring "migration 0019's fix for a
COUNT(*) race" in app/orders/order_number.py -- migration 0019 in the
current schema doc is files/file_access_log, not order numbers. That
citation was wrong; verify/fix the equivalent comment in
order_number.py too.)

Business date: the caller MUST pass a pre-computed business_date
(facility-timezone-local date), not UTC and not this module's own
clock read. This function used to hardcode Asia/Kolkata and compute
its own date, independently of whatever date the visit_number STRING
gets stamped with elsewhere -- two separate clock reads for the same
logical "today" that could disagree across a midnight boundary. There
is now exactly one business_date per request, computed once by the
caller and threaded through to both the counter and the number string.

facilities.timezone is NOT still pending -- it is already a live
column per §3-0002 (added in the v3.9 hardening pass). The backlog
entry in §8 referencing "IST assumed today" is stale documentation
debt left over from before that column shipped; don't treat it as
current status.
"""
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def next_visit_sequence(db: AsyncSession, facility_id: UUID, business_date: date) -> int:
    """
    Atomically allocates the next sequence number for
    (facility_id, business_date). Caller computes business_date from
    facilities.timezone -- see app/opd/service.py::_business_date().
    """
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

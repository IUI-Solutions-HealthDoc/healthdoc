"""backend/app/orders/order_number.py -- race-safe order number allocator: ORD-<YYYYMMDD>-<SEQ6>.
Same atomic INSERT ... ON CONFLICT pattern as app/opd/visit_number.py.
Counter is scoped by facility_id even though the number string itself
doesn't embed a facility code, to avoid cross-facility contention."""
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def next_order_sequence(db: AsyncSession, facility_id: UUID, business_date: date) -> int:
    result = await db.execute(
        text(
            "INSERT INTO order_number_counters (facility_id, counter_date, seq) "
            "VALUES (:facility_id, :d, 1) "
            "ON CONFLICT (facility_id, counter_date) DO UPDATE "
            "SET seq = order_number_counters.seq + 1 "
            "RETURNING seq"
        ),
        {"facility_id": str(facility_id), "d": business_date},
    )
    return result.scalar_one()


def format_order_number(business_date: date, seq: int) -> str:
    return f"ORD-{business_date:%Y%m%d}-{seq:06d}"

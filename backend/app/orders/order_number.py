from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def generate_order_number(db: AsyncSession) -> str:
    """Race-safe daily order number, e.g. ORD-20260724-000001.

    Uses order_number_counters (migration 0019), locked per-row with
    SELECT ... FOR UPDATE so concurrent requests serialize on today's
    row instead of racing on a COUNT(*) query.
    """
    today = datetime.now(timezone.utc).date()
    prefix = f"ORD-{today.strftime('%Y%m%d')}-"

    result = await db.execute(
        text(
            "INSERT INTO order_number_counters (counter_date, seq) "
            "VALUES (:d, 1) "
            "ON CONFLICT (counter_date) DO UPDATE "
            "SET seq = order_number_counters.seq + 1 "
            "RETURNING seq"
        ),
        {"d": today},
    )
    seq = result.scalar_one()
    return f"{prefix}{str(seq).zfill(6)}"

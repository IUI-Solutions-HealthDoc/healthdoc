"""The one correct way to ask "what is today, for this specific hospital?"
 
Never use date.today(), datetime.now().date(), or Postgres's CURRENT_DATE
for anything business-meaningful (token numbering, receipt dates, daily
counters). Those give the SERVER's current date, and the server runs on
UTC -- between midnight and 5:30 AM IST, a patient walking in gets
counted as part of yesterday's queue.
 
Computed in Postgres using the DB server's clock converted to the
facility's timezone -- not in Python, so it stays consistent with
created_at (which Postgres stamps itself).
"""
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import UTC, date, datetime, timedelta

from app.users.models import Facility


def latest_date_anywhere() -> date:
    """The furthest-ahead calendar date on Earth (UTC+14).

    For request validators, which run before any facility is known. Comparing
    against the server's UTC date instead rejects a genuine Indian "today"
    between midnight and 05:30 IST. This bound only catches the obviously
    impossible; the facility-exact check belongs where the facility is known.
    """
    return (datetime.now(UTC) + timedelta(hours=14)).date()


async def get_business_date(db: AsyncSession, facility_id: uuid.UUID) -> date:
    """(now() AT TIME ZONE facilities.timezone)::date, for one facility."""
    result = await db.execute(
        select(func.date(func.timezone(Facility.timezone, func.now())))
        .select_from(Facility)
        .where(Facility.id == facility_id)
    )
    business_date = result.scalar_one_or_none()
    if business_date is None:
        raise HTTPException(404, "Facility not found")
    return business_date

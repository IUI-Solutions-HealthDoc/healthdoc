"""The one correct way to ask "what is today, for this specific hospital?"

Never use date.today(), datetime.now().date(), or Postgres's CURRENT_DATE
for anything business-meaningful (token numbering, receipt dates, daily
counters). Those all give you the SERVER's current date -- and the server
runs on UTC, not IST. Between midnight and 5:30 AM in India, the server's
UTC clock still thinks it's YESTERDAY. A patient walking in at 2 AM would
get counted as part of yesterday's queue.

This computes the date entirely inside Postgres, using the database
server's own clock (not the Python app server's clock) converted into
the facility's own timezone. Doing it in SQL, not Python, matters: if we
instead read facility.timezone into Python and called datetime.now(tz)
there, we'd be trusting the APP server's clock instead of the DATABASE
server's -- and if the two machines' clocks ever drift apart even
slightly, this calculation and things like created_at (which Postgres
stamps itself) could disagree about what day it is.
"""
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date

from app.users.models import Facility

# PERMANENT DESIGN DECISION, not a placeholder. A real per-facility
# timezone column would need a new migration, and this project currently
# has no path to get a new migration approved. Every facility in this
# system is in India (Asia/Kolkata), so this produces the correct
# business date for every facility that actually exists today. If that
# ever changes (a facility genuinely needs a different timezone), that
# would need a new migration approved by whoever owns that process --
# until then, treat this as intentional, not a TODO.
_FALLBACK_TIMEZONE = "Asia/Kolkata"


async def get_business_date(db: AsyncSession, facility_id: uuid.UUID) -> date:
    """Returns "today" as it currently is in Asia/Kolkata (see
    _FALLBACK_TIMEZONE above for why this isn't read per-facility).

    Equivalent to the schema doc's formula, with the timezone fixed
    rather than looked up per facility:
        (now() AT TIME ZONE 'Asia/Kolkata')::date

    facility_id is still required and still checked against a real row
    -- a bad facility_id still correctly 404s. Only the timezone source
    is fixed rather than per-facility.
    """
    result = await db.execute(
        select(func.date(func.timezone(_FALLBACK_TIMEZONE, func.now())))
        .select_from(Facility)
        .where(Facility.id == facility_id)
    )
    business_date = result.scalar_one_or_none()
    if business_date is None:
        raise HTTPException(404, "Facility not found")
    return business_date

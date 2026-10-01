""""Today" as the queue service sees it in tests: the facility's own date.

Production asks Postgres for now() in facilities.timezone (common/business_date).
The SQLite fixture has no timezone(), so conftest fakes that call. The fake used
to answer date.today(), the runner's UTC date, while code that takes the
facility's timezone directly (appointment check-in) used the India date. From
18:30 to 24:00 UTC the two differ, and every CI run in that window failed.
Every test that means "the facility's today" uses this instead of date.today().
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

#: Facility.timezone's server default; the seed facilities never set another.
FACILITY_TZ = "Asia/Kolkata"


def business_today(timezone: str = FACILITY_TZ) -> date:
    return datetime.now(ZoneInfo(timezone)).date()

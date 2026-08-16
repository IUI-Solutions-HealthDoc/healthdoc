"""ipd module router — #216 (B3-W5-01).

app.main's MODULES list gates on "ipd" (not "admissions"), so this
re-exports app.admissions.router.router rather than duplicating the
endpoints. Business logic/models live in app/admissions/ (§3 0015/0023);
this file exists only so the auto-loader in app.main finds it.
"""
from app.admissions.router import router  # noqa: F401

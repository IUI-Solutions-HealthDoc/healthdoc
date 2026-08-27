"""ot module router — endpoints land here; see this module's GitHub issues."""
from fastapi import APIRouter, Depends

from app.auth.deps import require_roles
from app.ot import models  # noqa: F401 — registers OtSchedule/OtRecord on Base

router = APIRouter(prefix="/ot", tags=["ot"])


# Authenticated even though it returns no data. An unauthenticated
# endpoint on a health system is a finding regardless of payload, and
# `{"status": "stub"}` still discloses which modules exist and are
# unfinished — useful reconnaissance, useless to a legitimate caller.
@router.get("/ping", dependencies=[Depends(require_roles("admin"))])
async def ping() -> dict:
    return {"module": "ot", "status": "stub"}
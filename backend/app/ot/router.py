"""ot module router — endpoints land here; see this module's GitHub issues."""
from fastapi import APIRouter
from app.ot import models  # noqa: F401 — registers OtSchedule/OtRecord on Base

router = APIRouter(prefix="/ot", tags=["ot"])


@router.get("/ping")
async def ping() -> dict:
    return {"module": "ot", "status": "stub"}
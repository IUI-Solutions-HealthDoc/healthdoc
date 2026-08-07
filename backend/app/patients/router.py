"""patients module router — endpoints land here; see this module's GitHub issues."""
from fastapi import APIRouter
from app.patients import models  # noqa: F401 — registers Patient on Base.metadata

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("/ping")
async def ping() -> dict:
    return {"module": "patients", "status": "stub"}

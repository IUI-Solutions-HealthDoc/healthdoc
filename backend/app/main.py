"""HealthDoc API entrypoint — B1-W1-06 (skeleton, /health, envelope middleware)."""
import importlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.common.config import get_settings
from app.common.db import SessionLocal
from app.common.envelope import EnvelopeMiddleware
from app.common.mongo import get_mongo
from app.common.redis import get_redis

log = logging.getLogger("healthdoc")

MODULES = [
    "audit", "billing", "blood_bank", "consent", "departments", "emergency",
    "encounters", "files", "inventory", "ipd", "notifications", "nursing",
    "opd", "orders", "ot", "outbox", "pathology", "patients", "pharmacy",
    "queue", "radiology", "registration", "reports", "security_audit",
    "users", "wards",
]

settings = get_settings()


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Validate cryptographic configuration before serving traffic."""
    from app.common.security import _get_encryption_key, _get_hmac_key

    _get_encryption_key()
    _get_hmac_key()
    log.info("Crypto keys validated")
    yield


app = FastAPI(
    title="HealthDoc HMIS API",
    version="0.1.0",
    docs_url=f"{settings.api_prefix}/docs",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=_lifespan,
)
app.add_middleware(EnvelopeMiddleware)

# B1-W4-02: CORS locked to the Electron/desktop origin only (no wildcard).
# Extra origins (e.g. http://localhost:3000 for browser dev) come from settings.
_ALLOWED_ORIGINS = [
    "app://healthdoc",           # Electron packaged app custom scheme
    "https://localhost",         # nginx edge (browser dev)
] + [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


@app.get(f"{settings.api_prefix}/health")
async def health() -> dict:
    return {"status": "ok", "service": "healthdoc-api", "env": settings.environment}


@app.get(f"{settings.api_prefix}/health/deep")
async def health_deep() -> dict:
    checks: dict[str, str] = {}
    try:
        async with SessionLocal() as s:
            await s.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = f"error: {exc}"
    try:
        await get_mongo().command("ping")
        checks["mongo"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["mongo"] = f"error: {exc}"
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc}"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}


for name in MODULES:
    try:
        module = importlib.import_module(f"app.{name}.router")
        app.include_router(module.router, prefix=settings.api_prefix)
    except ModuleNotFoundError:
        log.warning("module app.%s has no router.py yet — skipped", name)

# B1-owned routers that don't live at app/<name>/router.py — included explicitly.
# NOTE: breakglass router is NOT registered yet — break_glass_grants (0004),
# data_access_log (0004), and notification_history (0020) are unmerged.
# Registering it would make the emergency path 500 with UndefinedTable.
# Re-add once #266 (0004) and #??? (0020) merge.
_B1_ROUTERS = [
    "app.integrations.abdm.identity.router",  # ABHA capture (W6-01)
]
for path in _B1_ROUTERS:
    try:
        mod = importlib.import_module(path)
        app.include_router(mod.router, prefix=settings.api_prefix)
    except ModuleNotFoundError as exc:
        log.warning("B1 router %s not importable: %s", path, exc)

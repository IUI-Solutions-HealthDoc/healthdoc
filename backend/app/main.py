"""HealthDoc API entrypoint — B1-W1-06 (skeleton, /health, envelope middleware)."""
import importlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.common.config import get_settings
from app.common.db import SessionLocal
from app.common.envelope import EnvelopeMiddleware
from app.common.mongo import get_mongo
from app.common.redis import get_redis
from app.common.storage import get_storage

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
async def lifespan(app: FastAPI):
    # Startup — runs once before the first request is served
    try:
        await get_storage().ensure_bucket()
        log.info("lifespan: MinIO bucket '%s' ready", settings.minio_bucket_files)
    except Exception as exc:  # noqa: BLE001
        # Non-fatal at startup — MinIO may not be reachable in CI/test
        # environments. The health/deep endpoint will surface the failure.
        log.warning("lifespan: MinIO bucket ensure failed — %s", exc)
    yield
    # Shutdown — nothing to clean up yet


app = FastAPI(
    title="HealthDoc HMIS API",
    version="0.1.0",
    docs_url=f"{settings.api_prefix}/docs",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(EnvelopeMiddleware)


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

    try:
        storage = get_storage()
        await storage.object_exists("__healthcheck__")
        checks["minio"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["minio"] = f"error: {exc}"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}


for name in MODULES:
    try:
        module = importlib.import_module(f"app.{name}.router")
        app.include_router(module.router, prefix=settings.api_prefix)
    except ModuleNotFoundError:
        log.warning("module app.%s has no router.py yet — skipped", name)

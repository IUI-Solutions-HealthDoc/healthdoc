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
from app.audit import listeners as _audit_listeners  # noqa: F401 — registers SQLAlchemy session hooks
from app.common.mongo import get_mongo
from app.common.redis import get_redis

log = logging.getLogger("healthdoc")

MODULES = [
    "allergies", "audit", "billing", "blood_bank", "consent", "departments",
    "emergency", "encounters", "files", "inventory", "ipd", "notifications",
    "nursing", "opd", "orders", "ot", "outbox", "pathology", "patients",
    "pharmacy", "queue", "radiology", "registration", "reports",
    "security_audit", "users", "wards",
]
# NB: "ipd" re-exports app.admissions.router — admissions is intentionally absent
# from this list. See app/ipd/router.py before concluding it is unmounted.

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


def _include(module_path: str, *, optional_name: str | None = None) -> None:
    """Mount one router.

    A bare `except ModuleNotFoundError` here used to swallow two very different
    things. "app.wards.router does not exist yet" is expected during build-out.
    "app.files.router exists but `import minio` inside it failed" is an outage:
    the whole module disappears from the API, with one WARNING line and a
    process that starts up perfectly healthy.

    That is how #233's file endpoints can be written, merged, tested and still
    be absent from a running server. So a missing *router module* is skipped,
    and anything else — a missing dependency, a typo in an import, a broken
    sibling module — is raised and stops the process.
    """
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        if optional_name is not None and exc.name == module_path:
            log.warning("module app.%s has no router.py yet — skipped", optional_name)
            return
        log.error("router %s failed to import: %s", module_path, exc)
        raise
    app.include_router(module.router, prefix=settings.api_prefix)


for name in MODULES:
    _include(f"app.{name}.router", optional_name=name)

# B1-owned routers that don't live at app/<name>/router.py — included explicitly.
_B1_ROUTERS = [
    "app.integrations.abdm.identity.router",  # ABHA capture (W6-01)
    # Break-glass (#391). This sat unregistered behind a note saying
    # break_glass_grants / data_access_log (0004) and notification_history (0020)
    # were unmerged and would 500 with UndefinedTable. All three merged — staging
    # is at 0041c — so the blocker was stale, not real. Emergency access is a NABH
    # DHS and DPDP control; having the audit tables without the enforcement path
    # is the worse half to be missing.
    "app.security_audit.breakglass",
]
for path in _B1_ROUTERS:
    _include(path)

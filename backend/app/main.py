"""HealthDoc API entrypoint — B1-W1-06 (skeleton, /health, envelope middleware)."""
import importlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.audit import (
    listeners as _audit_listeners,  # noqa: F401 — registers SQLAlchemy session hooks
)
from app.common.config import get_settings
from app.common.db import SessionLocal
from app.common.envelope import EnvelopeMiddleware
from app.common.metrics import MetricsMiddleware
from app.common.mongo import get_mongo
from app.common.redis import get_redis

log = logging.getLogger("healthdoc")

MODULES = [
    "allergies", "audit", "billing", "blood_bank", "consent", "departments",
    "diagnoses", "dpdp", "emergency", "encounters", "files", "inventory", "ipd", "notifications",
    "maintenance", "nursing", "opd", "orders", "ot", "outbox", "pathology", "patients", "procedures",
    "pharmacy", "queue", "radiology", "registration", "reports",
    "security_audit", "users", "wards",
]
# NB: "ipd" re-exports app.admissions.router — admissions is intentionally absent
# from this list. See app/ipd/router.py before concluding it is unmounted.

settings = get_settings()


def _assert_production_auth_hardening() -> None:
    """Refuse to serve production traffic with a development-grade auth config.

    Some hardening cannot be switched on by default without breaking every
    running dev stack — audience verification only works once the Keycloak
    realm emits a resource-server `aud`, and enabling it against a realm that
    does not locks out every user.

    The usual answer is a permissive default plus a comment asking someone to
    remember. This project has been bitten by exactly that: `verify_aud: False`
    carried a "tighten per-client in W2 hardening" note and was still there
    months later, and the OpenAPI schema shipped exposed because `environment`
    defaulted to "dev" and no production env file overrode it.

    So the permissive default stays for dev and becomes a HARD FAILURE in
    production. A misconfigured deployment does not start, which is loud, early
    and cheap — as opposed to passing an audit while accepting tokens minted
    for a different client.
    """
    if settings.environment.strip().lower() not in {"prod", "production"}:
        return

    missing = []
    if not settings.jwt_audience:
        missing.append(
            "JWT_AUDIENCE is unset — the `aud` claim is not verified, so a token "
            "issued to any other client in this realm would be accepted"
        )
    if missing:
        raise RuntimeError(
            "Refusing to start in production with development auth settings:\n  - "
            + "\n  - ".join(missing)
        )


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Validate cryptographic configuration before serving traffic."""
    from app.common.security import _get_encryption_key, _get_hmac_key

    _get_encryption_key()
    _get_hmac_key()
    log.info("Crypto keys validated")
    _assert_production_auth_hardening()
    yield


#: Interactive docs and the OpenAPI schema are DEV-ONLY.
#:
#: /openapi.json hands an attacker the complete inventory of this API: every
#: route, every parameter name and type, every response model. That is the
#: reconnaissance step of an assessment, and WASA scanners flag an exposed
#: schema as information disclosure — a finding that must be closed before a
#: Safe-to-Host certificate is issued.
#:
#: Gated on `environment` rather than removed, because the contract checker and
#: the frontend client generator both read /openapi.json locally. Anything
#: other than an explicit dev/test environment gets None, which makes FastAPI
#: serve 404 for all three routes: the default is closed.
_DOCS_ENVIRONMENTS = {"dev", "test", "local"}
_docs_enabled = settings.environment.strip().lower() in _DOCS_ENVIRONMENTS

app = FastAPI(
    title="HealthDoc HMIS API",
    version="0.1.0",
    docs_url=f"{settings.api_prefix}/docs" if _docs_enabled else None,
    redoc_url=f"{settings.api_prefix}/redoc" if _docs_enabled else None,
    openapi_url=f"{settings.api_prefix}/openapi.json" if _docs_enabled else None,
    lifespan=_lifespan,
)
app.add_middleware(EnvelopeMiddleware)
app.add_middleware(MetricsMiddleware)

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
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "If-Match",
        "X-Request-ID",
    ],
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


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Internal scrape target; production Nginx does not expose this route."""
    return Response(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
        headers={"Cache-Control": "no-store"},
    )


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


# Registered BEFORE the MODULES loop, and the order is load-bearing.
# app.users.router declares GET /users/{user_id}; whichever of the two is
# included first wins the match for "/users/me". Registered after, "me" is
# parsed as a UUID and the endpoint 422s — a failure that reads like a
# validation bug rather than a routing one. Keep this above the loop.
_include("app.users.me")
_include("app.users.account_request_router")

for name in MODULES:
    _include(f"app.{name}.router", optional_name=name)

# B1-owned routers that don't live at app/<name>/router.py — included explicitly.
_B1_ROUTERS = [
    # The four compliance ledgers that had no read path — see the module docstring.
    "app.audit.compliance_router",
    "app.common.capabilities_router",
    # facility_modules (0027) had no ORM model and no write path at all — module
    # gating was configurable only by direct SQL. See app/common/facility_modules.py.
    "app.common.facility_modules",
    "app.integrations.abdm.identity.router",  # ABHA capture (W6-01)
    "app.patients.portal_router",  # verified account-to-patient identity boundary (#228)
    "app.patients.portal_self_router",  # bound patient self-service reads (#228)
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

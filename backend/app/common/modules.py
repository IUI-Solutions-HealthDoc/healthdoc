"""Per-facility module toggles — enforcement helper.

Usage on any toggleable module router:

    from app.common.modules import require_module
    router = APIRouter(prefix="/radiology", tags=["radiology"],
                       dependencies=[Depends(require_module("radiology"))])

Rules (docs/database-schema.md §Module toggle behavior):
- No facility_modules row  => module ENABLED (default-on).
- Disabled                 => 409 {"code": "module_disabled", "module": ...}
- Core modules are never gated — do not wrap them with this.
"""
from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.common.cache import get_json, set_json
from app.common.db import get_db
from app.common.enums import ModuleCode

# Core = everything that is NOT in ModuleCode. Never gate these.
CORE_MODULES = frozenset({
    "patients", "registration", "opd", "encounters", "queue", "departments",
    "billing", "consent", "audit", "files", "users", "notifications",
    "inventory", "ipd", "emergency", "patient_portal", "abdm",
    "orders", "procedures", "nursing", "wards", "reports", "outbox", "security_audit",
})
_DB_DEPENDENCY = Depends(get_db)


async def get_capabilities(db: AsyncSession, facility_id) -> dict[str, bool]:
    """All toggleable modules with their enabled state for a facility."""
    cache_identity = str(facility_id)
    cached = await get_json("facility-capabilities", cache_identity)
    if isinstance(cached, dict) and set(cached) == set(ModuleCode.values()):
        return {code: bool(enabled) for code, enabled in cached.items()}

    rows = await db.execute(
        text("SELECT module_code, is_enabled FROM facility_modules WHERE facility_id = :f"),
        {"f": str(facility_id)},
    )
    overrides = dict(rows.all())
    capabilities = {m.value: overrides.get(m.value, True) for m in ModuleCode}
    await set_json("facility-capabilities", cache_identity, capabilities, ttl=300)
    return capabilities


def require_module(module_code: str):
    if module_code in CORE_MODULES:
        raise ValueError(f"'{module_code}' is a core module — never gate it")
    ModuleCode(module_code)  # raises if unknown

    async def _check(user: CurrentUser, db: AsyncSession = _DB_DEPENDENCY) -> None:
        row = await db.execute(
            text("""SELECT fm.is_enabled FROM facility_modules fm
                    JOIN users u ON u.facility_id = fm.facility_id
                    WHERE u.keycloak_sub = :sub AND fm.module_code = :m"""),
            {"sub": user.sub, "m": module_code},
        )
        enabled = row.scalar_one_or_none()
        if enabled is False:  # no row (None) = enabled
            raise HTTPException(
                status_code=409,
                detail={"code": "module_disabled", "module": module_code},
            )

    return _check

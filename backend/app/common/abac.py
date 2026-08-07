"""ABAC evaluation hook (B1-W2-02) — runs AFTER RBAC (require_roles).

RBAC answers "does this role exist on the user?"; ABAC answers "given the row's
attributes, is this specific action allowed?". Policies live in the `policies` table
(migration 0029) and are matched against a small attribute dict the caller passes.

Usage in a module service:
    from app.common.abac import enforce_if_policy_exists
    await enforce_if_policy_exists(db, user, action="read", resource_type="patients",
                  attrs={"facility_id": row.facility_id})

If no policy exists the system falls back to RBAC's decision. Once a policy matches,
explicit denies and unevaluable conditions deny.

TODO(#issue-0003): log every policy evaluation to audit_logs once migration 0003 lands.
"""
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AuthUser


async def evaluate(
    db: AsyncSession, user: AuthUser, *, action: str, resource_type: str,
    attrs: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """Evaluate ABAC policies. Returns (allowed, reason). reason is non-None on deny.

    IMPORTANT — fail-open path: if NO policy rows match the (role, resource_type,
    action) triple, this returns (True, None) — i.e. it defers to RBAC and does NOT
    assert that ABAC approved the request. Callers must not treat a True return as
    "ABAC checked and approved"; it may simply mean "no ABAC policy exists for this
    action". Tighten to deny-all in W7 hardening once all modules have policies.
    """
    attrs = attrs or {}
    rows = await db.execute(
        text("""SELECT effect, condition FROM policies
                WHERE is_active AND resource_type = :rt AND action = :act
                  AND subject_role = ANY(:roles)"""),
        {"rt": resource_type, "act": action, "roles": user.roles},
    )
    matched = rows.all()
    if not matched:
        # FAIL-OPEN: no ABAC policy for this triple — defer to RBAC.
        # This does NOT mean ABAC approved. See docstring above.
        return True, None
    user_facility_id = None
    if any(condition for _, condition in matched):
        user_row = await db.execute(
            text("SELECT facility_id FROM users WHERE keycloak_sub = :sub"),
            {"sub": user.sub},
        )
        user_facility_id = user_row.scalar_one_or_none()

    # explicit deny wins; unevaluable conditions deny (never fail open)
    allow = False
    for effect, condition in matched:
        holds = _condition_holds(condition, user_facility_id, attrs)
        if holds is None:
            # Unevaluable condition — deny and say why
            return False, f"unevaluable condition: {condition}"
        if holds:
            if effect == "deny":
                return False, f"explicit deny by policy condition: {condition}"
            allow = True
    return allow, (None if allow else "no matching allow policy")


def _condition_holds(
    condition: dict | None, user_facility_id: Any, attrs: dict,
) -> bool | None:
    """Returns True (holds), False (doesn't hold), or None (unevaluable)."""
    if not condition:
        return True
    unknown = set(condition) - {"same_facility"}
    if unknown:
        return None
    if condition.get("same_facility"):
        if attrs.get("facility_id") is None or user_facility_id is None:
            return None  # unevaluable — required attrs missing
        if str(user_facility_id) != str(attrs.get("facility_id")):
            return False
    return True


async def enforce_if_policy_exists(db: AsyncSession, user: AuthUser, **kw: Any) -> None:
    """Enforce ABAC — but only if a matching policy exists.

    Named explicitly to signal that a True return does NOT mean 'ABAC approved';
    it may mean 'no policy exists'. Rename to enforce() once the posture flips
    to deny-all in W7 hardening.
    """
    allowed, reason = await evaluate(db, user, **kw)
    if not allowed:
        raise HTTPException(403, {"code": "abac_denied",
                                  "action": kw.get("action"),
                                  "resource": kw.get("resource_type"),
                                  "reason": reason})

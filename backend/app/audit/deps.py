"""
Actor-context dependency for the audit module — fills in
app/audit/context.py per request.

Repo path: backend/app/audit/deps.py

REPLACES middleware.py. Now that app/auth/deps.py is visible: auth here
is dependency-based (get_current_user / require_roles), not
middleware-based. Starlette's BaseHTTPMiddleware runs BEFORE FastAPI's
Depends() chain resolves, so a plain HTTP middleware genuinely cannot
see the authenticated user in this repo's setup — middleware.py's
"Option A" (decode the JWT again inside middleware) would have meant
duplicating and re-verifying the token a second time for no reason.
This dependency runs alongside your existing auth chain instead, so it
sees the same resolved user require_roles() already checked.

IMPORTANT GAP this file surfaces, not hides:
get_current_user() only decodes the JWT — it returns
AuthUser(sub, username, roles), where `sub` is the Keycloak subject
string. It does NOT look up the app's own users.id (a UUID). But
audit_logs.user_id is a UUID FOREIGN KEY to users.id (schema doc §3
0002: "users.keycloak_sub varchar(64) UNIQUE NOT NULL -- Keycloak
subject; JWT 'sub' maps here"). So this dependency does that lookup
itself — one extra DB query per protected request.

Tech Lead review answered both open questions from the previous PR:

  - No users row for a valid keycloak_sub -> 403, not a warning. A
    token whose profile doesn't exist can't be attributed, so the
    mutation must not proceed. Raised here as a plain HTTPException so
    it happens before any business mutation runs.
  - role -> the role the action was taken UNDER, not every role the
    user holds. A comma-joined list makes "who was acting as what"
    unanswerable in an audit trail. _select_acting_role() below picks
    the highest-privilege match from a fixed priority order; this is a
    placeholder ordering (see its docstring) until an endpoint-scoped
    "acting role" concept exists.

This dependency does NOT do authorization — require_roles() still owns
the actual 401/403 decision for whether the request is allowed at all.
This only captures context for audit rows, plus the identity-resolution
403 above (a request with no attributable actor is never allowed to
mutate, independent of what require_roles() would have said).
"""
from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditActor, set_current_actor
from app.auth.deps import AuthUser, get_current_user
from app.common.db import get_db

logger = logging.getLogger(__name__)

# Highest-to-lowest privilege, used only to pick which single role an
# action was taken "under" when a user's token carries several realm
# roles (see _select_acting_role()). Order matches the authority roles
# in schema doc §Account governance plus the remaining realm roles;
# unrecognised roles sort after all of these.
_ROLE_PRIORITY: tuple[str, ...] = (
    "superadmin",
    "admin",
    "hod",
    "supervisor",
    "auditor",
    "doctor",
    "nurse",
    "lab_tech",
    "radiology_tech",
    "pharmacist",
    "emergency",
    "receptionist",
    "patient",
)


def _select_acting_role(roles: list[str]) -> str | None:
    """
    Picks ONE role to record as "acting under" for this request, instead
    of joining all of a user's roles with commas — see module docstring.

    This is a stand-in for a real "acting role" concept: today it just
    takes the highest-privilege role the token carries, which is right
    for most single-role staff accounts but not necessarily right for
    someone with multiple roles doing a role-specific action (e.g. an
    admin who is also a doctor, placing an order as a doctor). Flag for
    Tech Lead if endpoints need to declare their own expected role
    instead of relying on this global ordering.
    """
    if not roles:
        return None
    for candidate in _ROLE_PRIORITY:
        if candidate in roles:
            return candidate
    return roles[0]


def _extract_ip(request: Request) -> str | None:
    # Respect a reverse proxy's forwarded header if present (nginx/ingress),
    # otherwise fall back to the direct connecting client.
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


async def get_current_actor_dependency(
    request: Request,
    user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AuditActor:
    """
    Resolves the JWT's `sub` -> users.id, builds an AuditActor, stores it
    in the request-scoped context (app/audit/context.py) so write_audit_log()
    picks it up automatically, and also returns it in case a route wants
    it directly.

    Usage — add alongside require_roles() on any route that mutates data:

        @router.post(
            "/",
            dependencies=[Depends(require_roles("receptionist", "admin"))],
        )
        async def create_thing(
            actor: AuditActor = Depends(get_current_actor_dependency),
            session: AsyncSession = Depends(get_db),
        ):
            ...
    """
    # Raw SQL here (not an ORM select) to avoid app.audit importing
    # app.users.models — sidesteps a cross-module import cycle. If a
    # shared users table reference already exists somewhere common,
    # swap this for a real ORM select instead.
    result = await session.execute(
        text("SELECT id FROM users WHERE keycloak_sub = :sub"),
        {"sub": user.sub},
    )
    row = result.first()

    if row is None:
        # Tech Lead: 403, not a warning -- a token whose profile doesn't
        # exist can't be attributed, so the mutation must not proceed.
        logger.warning(
            "get_current_actor_dependency: no users row for keycloak_sub=%s — "
            "rejecting request, cannot attribute an audit row to this actor",
            user.sub,
        )
        raise HTTPException(
            status_code=403,
            detail={"code": "actor_not_provisioned"},
        )

    user_id = row.id

    # audit_logs.role records the role the action was taken UNDER, not
    # every role the user holds (see _select_acting_role() docstring).
    role = _select_acting_role(user.roles)

    actor = AuditActor(
        user_id=user_id,
        role=role,
        ip_address=_extract_ip(request),
        device_id=request.headers.get("x-device-id"),
    )
    set_current_actor(actor)
    return actor

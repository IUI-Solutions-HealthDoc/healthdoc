"""Session start and end audit (POST /audit/session/login and /logout).

Split from app/audit/router.py so both deployments mount it: the hospital API
and the separate control-room API (HEALTHDOC_API_MODE=control_room), where the
rest of the audit router, the auditor's tools, must not be served.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import events
from app.auth.deps import AuthUser, CurrentUser, DbUser, get_current_db_user
from app.common.db import get_db

router = APIRouter(prefix="/audit", tags=["audit"])
log = logging.getLogger(__name__)


async def _session_actor(jwt_user: AuthUser, db: AsyncSession, event: str, request: Request) -> DbUser | None:
    """The facility user to record a session event against, or None for a
    control-room officer.

    An officer (realm role `monitor`, docs/control-room-design-2026-10-10.md)
    works for no hospital, so has no users row and no facility to file an
    audit row under (audit_logs.facility_id is NOT NULL). Their session events
    go to the application log, from the token's own identity, like their board
    reads. Anyone else without a users row is still refused, as before.
    """
    if "monitor" in jwt_user.roles and not await _has_users_row(db, jwt_user.sub):
        log.info(
            "monitor session %s", event,
            extra={"monitor_sub": jwt_user.sub, "monitor_username": jwt_user.username,
                   "ip_address": request.client.host if request.client else None},
        )
        return None
    return await get_current_db_user(jwt_user, db)


async def _has_users_row(db: AsyncSession, sub: str) -> bool:
    from app.users.models import User  # local import, as in auth.deps

    return (await db.execute(select(User.id).where(User.keycloak_sub == sub))).first() is not None


@router.post("/session/login", status_code=202)
async def record_login(
    request: Request,
    jwt_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record that this user's session started.

    WHY THIS ENDPOINT EXISTS AT ALL. Authentication happens in Keycloak, not
    here — this backend only ever sees a bearer token on an already-established
    session, so there is no natural point at which it can observe a login. That
    is why events.log_login() was written and never called: there was nowhere
    to call it from.

    The honest options were a Keycloak event listener or a client that says
    "I have just signed in". This is the second. It is attributable — the row
    is written from the token's own identity, never from the body — and its
    weakness is stated rather than hidden: a client that never calls it simply
    produces no login row. It cannot be forged into someone else's name, which
    is the property that matters for an audit trail.

    Deliberately NOT role-gated beyond authentication: every role logs in, and
    a login that goes unrecorded because the role list was not updated is the
    failure this is meant to end.
    """
    user = await _session_actor(jwt_user, db, "login", request)
    if user is None:
        return {"recorded": "login", "where": "application_log"}
    await events.log_login(
        db,
        facility_id=user.facility_id,
        user_id=user.id,
        ip_address=request.client.host if request.client else None,
    )
    return {"recorded": "login"}


@router.post("/session/logout", status_code=202)
async def record_logout(
    request: Request,
    jwt_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record that this user signed out. Same reasoning as the login route."""
    user = await _session_actor(jwt_user, db, "logout", request)
    if user is None:
        return {"recorded": "logout", "where": "application_log"}
    await events.log_logout(
        db,
        facility_id=user.facility_id,
        user_id=user.id,
        ip_address=request.client.host if request.client else None,
    )
    return {"recorded": "logout"}

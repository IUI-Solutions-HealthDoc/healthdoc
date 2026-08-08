"""Keycloak JWT verification — FastAPI dependencies.

Usage in any module router:
    from app.auth.deps import CurrentUser, require_roles

    @router.get("/", dependencies=[Depends(require_roles("receptionist", "admin"))])
    async def list_things(user: CurrentUser): ...

Two different "user" objects live here, and picking the wrong one is the most
frequently repeated bug on this project:

    CurrentUser   -> AuthUser, decoded from the JWT. `.sub` is the KEYCLOAK
                     SUBJECT. It is NOT users.id and must never be written to
                     a column that foreign-keys to users.id.
    CurrentDbUser -> the app's own `users` row. `.id` IS users.id, and `.facility_id`
                     is the authenticated user's facility — use it for facility
                     scoping rather than trusting a value from the request body.

Storing `sub` where `users.id` belongs has produced three separate defects:
lab dual-verification silently never matched (#260), and two FK violations on
writes (#310, #311). Anything that records "who did this" wants CurrentDbUser.
"""
import time
import uuid
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.config import get_settings
from app.common.db import get_db

_bearer = HTTPBearer(auto_error=False)
_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}
JWKS_TTL_SECONDS = 3600


class AuthUser(BaseModel):
    sub: str
    username: str = ""
    roles: list[str] = []

    amr: list[str] = []


async def _get_jwks() -> dict:
    if _jwks_cache["keys"] and time.time() - _jwks_cache["fetched_at"] < JWKS_TTL_SECONDS:
        return _jwks_cache["keys"]
    url = f"{get_settings().jwt_issuer}/protocol/openid-connect/certs"
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    _jwks_cache.update(keys=resp.json(), fetched_at=time.time())
    return _jwks_cache["keys"]


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        claims = jwt.decode(
            creds.credentials,
            await _get_jwks(),
            algorithms=["RS256"],
            issuer=get_settings().jwt_issuer,
            options={"verify_aud": False},  # tighten per-client in W2 hardening
        )
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc
    return AuthUser(
        sub=claims["sub"],
        username=claims.get("preferred_username", ""),
        roles=claims.get("realm_access", {}).get("roles", []),

        amr=claims.get("amr", []),
    )


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]


def require_roles(*allowed: str):
    async def _check(user: CurrentUser) -> AuthUser:
        if not set(allowed) & set(user.roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires one of: {allowed}")
        return user

    return _check


class DbUser(BaseModel):
    """The app-side `users` row for the caller. `id` is users.id — the value that
    belongs in created_by/updated_by/performed_by and anything FK'd to users."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    keycloak_sub: str
    username: str
    facility_id: uuid.UUID
    roles: list[str] = []


async def get_current_db_user(
    jwt_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DbUser:
    """Resolve the JWT subject to the app's own users row.

    Deliberately NOT cached. A token stays valid until it expires, so if this
    were memoised a user deactivated mid-shift would keep writing until their
    token ran out. One indexed lookup on a UNIQUE column per request is the
    right price for revocation taking effect immediately.

    Two distinct 403s rather than one, because the operational fix differs:
    `actor_not_provisioned` means someone authenticated in Keycloak but has no
    profile here (an admin has to create it); `user_deactivated` means the
    profile exists and was switched off (intended, no action needed).

    Roles come from the token, not the database — Keycloak is the authority on
    roles, and `users` deliberately has no role column.
    """
    from app.users.models import User  # local import keeps auth free of a model cycle

    row = (
        await db.execute(
            select(User.id, User.keycloak_sub, User.username, User.facility_id, User.is_active)
            .where(User.keycloak_sub == jwt_user.sub)
        )
    ).first()

    if row is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "actor_not_provisioned",
             "detail": "Authenticated, but no user profile exists for this account"},
        )
    if not row.is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "user_deactivated", "detail": "This account has been deactivated"},
        )

    return DbUser(
        id=row.id,
        keycloak_sub=row.keycloak_sub,
        username=row.username,
        facility_id=row.facility_id,
        roles=jwt_user.roles,
    )


CurrentDbUser = Annotated[DbUser, Depends(get_current_db_user)]

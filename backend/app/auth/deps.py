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
import logging
import time
import uuid
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError, PyJWKSet
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.config import get_settings
from app.common.db import get_db

log = logging.getLogger("healthdoc.auth")

_bearer = HTTPBearer(auto_error=False)
_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}
JWKS_TTL_SECONDS = 3600

DbSession = Annotated[AsyncSession, Depends(get_db)]


class AuthUser(BaseModel):
    sub: str
    username: str = ""
    roles: list[str] = []

    amr: list[str] = []


async def _get_jwks() -> dict:
    if _jwks_cache["keys"] and time.time() - _jwks_cache["fetched_at"] < JWKS_TTL_SECONDS:
        return _jwks_cache["keys"]
    settings = get_settings()
    url = settings.jwt_jwks_url or (
        f"{settings.jwt_issuer}/protocol/openid-connect/certs"
    )
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    _jwks_cache.update(keys=resp.json(), fetched_at=time.time())
    return _jwks_cache["keys"]


def _signing_key(token: str, jwks: dict):
    """Pick the JWKS key matching this token's `kid`.

    python-jose accepted the whole JWKS and chose internally. PyJWT wants one
    key, which is an improvement: selecting by `kid` explicitly means an
    unexpected key never gets tried, and a token whose `kid` we do not publish
    is refused rather than quietly matched against something else.
    """
    kid = jwt.get_unverified_header(token).get("kid")
    if not kid:
        raise InvalidTokenError("token header carries no kid")
    for key in PyJWKSet.from_dict(jwks).keys:
        if key.key_id == kid:
            return key.key
    raise InvalidTokenError("no JWKS key matches this token's kid")


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    settings = get_settings()
    token = creds.credentials
    try:
        jwks = await _get_jwks()
        # AUDIENCE. `jwt_audience` unset means the aud claim is not checked,
        # which is what python-jose was doing behind `verify_aud: False` and a
        # "tighten later" comment. Unverified aud means a token minted for ANY
        # other client in this realm is accepted here.
        #
        # It is not enabled by default because it only works once the realm
        # emits the right audience, and turning it on against a Keycloak that
        # does not would lock every user out. app/main.py refuses to start in
        # production while it is unset, so the gap cannot reach an environment
        # that matters — see _assert_production_auth_hardening there.
        audience = settings.jwt_audience or None
        claims = jwt.decode(
            token,
            _signing_key(token, jwks),
            algorithms=["RS256"],
            issuer=settings.jwt_issuer,
            audience=audience,
            options={
                "verify_aud": audience is not None,
                # PyJWT does not require these by default. A token with no exp
                # never expires, and one with no sub has no subject to scope by.
                "require": ["exp", "iat", "sub"],
            },
        )
    except InvalidTokenError as exc:
        # The reason goes to the log, never to the caller. The old message was
        # f"Invalid token: {exc}", which tells an attacker probing with forged
        # tokens exactly which check failed — signature vs expiry vs issuer is
        # a free oracle for narrowing an attack.
        log.warning("JWT rejected: %s", type(exc).__name__)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    except httpx.HTTPError as exc:
        # JWKS unreachable is OUR outage, not the caller's bad credential.
        # Returning 401 would tell every user their login is broken.
        log.error("JWKS fetch failed during token verification: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Identity provider unavailable"
        ) from exc

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
    # Department-scoped roles (notably HOD) must not trust a department id
    # supplied in a route. Nullable for facility-wide roles such as admin.
    department_id: uuid.UUID | None = None
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
            select(
                User.id,
                User.keycloak_sub,
                User.username,
                User.facility_id,
                User.department_id,
                User.is_active,
            )
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
        department_id=row.department_id,
        roles=jwt_user.roles,
    )


CurrentDbUser = Annotated[DbUser, Depends(get_current_db_user)]

"""Keycloak JWT verification — FastAPI dependencies.

Usage in any module router:
    from app.auth.deps import CurrentUser, require_roles

    @router.get("/", dependencies=[Depends(require_roles("receptionist", "admin"))])
    async def list_things(user: CurrentUser): ...
"""
import time
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.common.config import get_settings

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

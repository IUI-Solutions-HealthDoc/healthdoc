"""Keycloak Admin API sync — users exist in BOTH Keycloak (credentials/roles)
and Postgres (profile). Create/disable flows go through here."""
import httpx
from fastapi import HTTPException

from app.common.config import get_settings


class KeycloakAdmin:
    def __init__(self) -> None:
        s = get_settings()
        self.base = s.keycloak_base_url.rstrip("/")
        self.realm = s.keycloak_realm
        self.admin_user = s.keycloak_admin
        self.admin_password = s.keycloak_admin_password

    async def _token(self, client: httpx.AsyncClient) -> str:
        resp = await client.post(
            f"{self.base}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": self.admin_user,
                "password": self.admin_password,
            },
        )
        if resp.status_code != 200:
            raise HTTPException(502, "Keycloak admin auth failed")
        return resp.json()["access_token"]

    async def create_user(
        self, username: str, full_name: str, email: str | None,
        temporary_password: str, roles: list[str],
    ) -> str:
        """Creates the Keycloak user + assigns realm roles. Returns keycloak_sub."""
        async with httpx.AsyncClient(timeout=10) as client:
            token = await self._token(client)
            headers = {"Authorization": f"Bearer {token}"}
            base = f"{self.base}/admin/realms/{self.realm}"

            first, _, last = full_name.partition(" ")
            resp = await client.post(f"{base}/users", headers=headers, json={
                "username": username,
                "email": email,
                "firstName": first,
                "lastName": last or "-",
                "enabled": True,
                "credentials": [{"type": "password", "value": temporary_password,
                                 "temporary": True}],
            })
            if resp.status_code == 409:
                raise HTTPException(409, f"Keycloak user '{username}' already exists")
            if resp.status_code not in (200, 201):
                raise HTTPException(502, f"Keycloak user create failed: {resp.text[:200]}")
            sub = resp.headers["Location"].rsplit("/", 1)[-1]

            if roles:
                all_roles = (await client.get(f"{base}/roles", headers=headers)).json()
                wanted = [r for r in all_roles if r["name"] in roles]
                missing = set(roles) - {r["name"] for r in wanted}
                if missing:
                    raise HTTPException(422, f"Unknown realm roles: {sorted(missing)}")
                resp = await client.post(
                    f"{base}/users/{sub}/role-mappings/realm", headers=headers, json=wanted
                )
                if resp.status_code not in (200, 204):
                    raise HTTPException(502, "Keycloak role assignment failed")
            return sub

    async def set_enabled(self, keycloak_sub: str, enabled: bool) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            token = await self._token(client)
            resp = await client.put(
                f"{self.base}/admin/realms/{self.realm}/users/{keycloak_sub}",
                headers={"Authorization": f"Bearer {token}"},
                json={"enabled": enabled},
            )
            if resp.status_code not in (200, 204):
                raise HTTPException(502, "Keycloak enable/disable failed")

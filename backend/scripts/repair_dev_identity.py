"""Preview/repair one explicitly identified, orphaned local development identity.

Never a login fallback: matching usernames alone cannot rebind a real account.
The operator supplies the existing staff UUID and both observed subjects. Only
known dev accounts in the seeded facility and local realm are eligible. This
changes no password, role, profile field, consent or clinical attribution.
"""

import argparse
import asyncio
import json
import logging
import uuid

import httpx
from fastapi import HTTPException
from sqlalchemy import select, text, update

from app.audit.service import write_audit_log
from app.common.config import get_settings
from app.common.db import SessionLocal
from app.users.models import User
from app.users.service import KeycloakAdmin
from scripts.seed_dev_data import DISPLAY_NAMES, FACILITY_ID

DEV_ROLES = {
    "dev.doctor": "doctor", "dev.admin": "admin", "dev.receptionist": "receptionist",
}


class RepairRefused(ValueError):
    pass


def validate_environment(settings):
    if (
        settings.environment != "dev"
        or settings.keycloak_realm != "healthdoc"
        or settings.keycloak_base_url.rstrip("/") not in {
            "http://keycloak:8080/auth", "http://localhost:8081/auth",
        }
    ):
        raise RepairRefused("Only the explicit local development realm is supported")


async def repair(
    db, client, kc, *, username, user_id, old_subject, new_subject, apply=False,
):
    if username not in DEV_ROLES or old_subject == new_subject:
        raise RepairRefused("An eligible account and distinct observed subjects are required")
    statement = select(User).where(User.id == user_id)
    if apply:
        statement = statement.with_for_update()
    row = (await db.execute(statement)).scalar_one_or_none()
    if (
        row is None or row.username != username or row.facility_id != FACILITY_ID
        or row.full_name != DISPLAY_NAMES[username] or not row.is_active
        or row.keycloak_sub != str(old_subject)
    ):
        raise RepairRefused("Existing active dev profile does not match the reviewed identity")
    collision = await db.scalar(select(User.id).where(User.keycloak_sub == str(new_subject)))
    if collision is not None:
        raise RepairRefused("Replacement subject already belongs to a staff profile")

    token = await kc._token(client)
    headers = {"Authorization": f"Bearer {token}"}
    base = f"{kc.base}/admin/realms/{kc.realm}"
    response = await client.get(f"{base}/users", params={"username": username, "exact": "true"}, headers=headers)
    response.raise_for_status()
    users = response.json()
    if not isinstance(users, list) or len(users) != 1:
        raise RepairRefused("Expected exactly one matching realm account")
    account = users[0]
    name = " ".join([account.get("firstName", ""), account.get("lastName", "")]).strip()
    if (
        account.get("id") != str(new_subject) or account.get("username") != username
        or account.get("enabled") is not True or name != row.full_name
        or account.get("federationLink")
    ):
        raise RepairRefused("Realm account does not match the reviewed active local identity")
    previous = await client.get(f"{base}/users/{old_subject}", headers=headers)
    if previous.status_code != 404:
        raise RepairRefused("Old realm identity still exists or cannot be checked")
    response = await client.get(f"{base}/users/{new_subject}/role-mappings/realm/composite", headers=headers)
    response.raise_for_status()
    roles = {role["name"] for role in response.json()}
    if roles != {DEV_ROLES[username]}:
        raise RepairRefused("Realm roles differ from the expected single development role")

    if apply:
        # Bulk update plus explicit audit: leave every clinical FK and all staff
        # metadata untouched. The caller commits both together, never separately.
        await db.execute(update(User).where(
            User.id == user_id, User.keycloak_sub == str(old_subject),
        ).values(keycloak_sub=str(new_subject)))
        await write_audit_log(
            db, facility_id=row.facility_id, action="update", resource_type="users",
            resource_id=row.id, old_value={"keycloak_sub": str(old_subject)},
            new_value={"keycloak_sub": str(new_subject)},
            reason="Explicit local operator repair of orphaned dev identity; staff ID and roles preserved",
        )
    return {"username": username, "eligible": True, "applied": apply, "staff_id_preserved": True}


async def run(args):
    # Ensure all FK target models and audit listeners are registered in the CLI.
    from app import main as app_main  # noqa: F401

    settings = get_settings()
    validate_environment(settings)
    async with SessionLocal() as db, httpx.AsyncClient(timeout=10) as client:
        if not args.apply:
            await db.execute(text("SET TRANSACTION READ ONLY"))
        # Preview does not lock or mutate; apply locks and rechecks everything.
        result = await repair(
            db, client, KeycloakAdmin(), username=args.username, user_id=args.user_id,
            old_subject=args.old_subject, new_subject=args.new_subject, apply=args.apply,
        )
        if args.apply:
            await db.commit()
        else:
            await db.rollback()
        print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", choices=DEV_ROLES, required=True)
    parser.add_argument("--user-id", type=uuid.UUID, required=True)
    parser.add_argument("--old-subject", type=uuid.UUID, required=True)
    parser.add_argument("--new-subject", type=uuid.UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(run(args))
    except RepairRefused as exc:
        # All refusal text above is fixed copy, never upstream response data.
        parser.exit(1, f"Identity repair refused: {exc}\n")
    except (httpx.HTTPError, HTTPException) as exc:
        parser.exit(1, f"Identity repair refused: {type(exc).__name__}\n")

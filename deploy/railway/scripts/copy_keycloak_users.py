#!/usr/bin/env python3
"""Copy HealthDoc staff logins from the PC's Keycloak to the Railway one.

WHY THIS EXISTS INSTEAD OF A DATABASE DUMP
The local stack runs Keycloak in `start-dev`, whose H2 database lives inside
the container itself (no volume, which is why it must never be recreated).
There is no database to pg_dump, and `kc.sh export` contends with the running
server for that file. The admin REST API can be read safely while it runs.

WHY THE IDS MUST SURVIVE
`users.keycloak_sub` in HealthDoc's PostgreSQL is the Keycloak user id, and
every request is resolved by it (app/auth/deps.py). Users recreated with new
ids would sign in and then 401 on every call. Partial import keeps the `id`
it is given, so the restored HealthDoc rows keep matching.

WHAT IS NOT COPIED, ON PURPOSE
Passwords. The PC's accounts use `devpass`, which cannot go onto a public
address. Each copied user gets a random temporary password, written only to
the local file named by --passwords-out (mode 0600), and must change it and
enrol TOTP at first sign-in.

    # 1. On the Mac, read-only against the local Keycloak:
    python3 copy_keycloak_users.py export \
        --source http://127.0.0.1:8081/auth --admin-user admin \
        --out kc-users.json --passwords-out kc-temp-passwords.txt
    # 2. Against the Railway Keycloak (temporary Railway domain on the keycloak
    #    service; remove the domain afterwards):
    python3 copy_keycloak_users.py import \
        --target https://<keycloak-temp-domain>/auth --admin-user admin --file kc-users.json

The admin password is read from KEYCLOAK_ADMIN_PASSWORD, never from argv.
Standard library only, so it runs on a stock macOS Python.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

REALM = "healthdoc"
# Keycloak's own bookkeeping roles; the target realm already has them.
_BUILTIN_ROLE_PREFIXES = ("default-roles-", "offline_access", "uma_authorization")
_USER_FIELDS = ("id", "username", "enabled", "firstName", "lastName", "email", "emailVerified", "attributes")


def _context(url: str) -> ssl.SSLContext | None:
    # The PC's nginx uses a self-signed certificate; the REST port used here is
    # plain HTTP on loopback. Never disable verification for a remote target.
    return None if url.startswith("http://") else ssl.create_default_context()


def _token(base: str, user: str, password: str) -> str:
    body = urllib.parse.urlencode(
        {"grant_type": "password", "client_id": "admin-cli", "username": user, "password": password}
    ).encode()
    req = urllib.request.Request(f"{base}/realms/master/protocol/openid-connect/token", data=body)
    with urllib.request.urlopen(req, context=_context(base), timeout=30) as resp:
        return json.load(resp)["access_token"]


def _call(base: str, token: str, path: str, method: str = "GET", payload: object | None = None) -> object:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{base}/admin/realms/{REALM}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, context=_context(base), timeout=60) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def _admin_password() -> str:
    password = os.environ.get("KEYCLOAK_ADMIN_PASSWORD")
    if not password:
        sys.exit("Set KEYCLOAK_ADMIN_PASSWORD in the environment (it is not taken as an argument).")
    return password


def _private(path: str):
    """Open for writing, created 0600 from the start (not chmod after)."""
    return open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8")


def export(args: argparse.Namespace) -> None:
    token = _token(args.source, args.admin_user, _admin_password())
    users, first = [], 0
    while True:
        page = _call(args.source, token, f"/users?first={first}&max=100&briefRepresentation=false")
        if not page:
            break
        users.extend(page)
        first += len(page)

    out_users, passwords = [], []
    for user in users:
        if user.get("serviceAccountClientId"):
            continue  # belongs to a client; the target realm defines its own
        roles = _call(args.source, token, f"/users/{user['id']}/role-mappings/realm") or []
        realm_roles = sorted(r["name"] for r in roles if not r["name"].startswith(_BUILTIN_ROLE_PREFIXES))
        temp = secrets.token_urlsafe(12) + "aA1!"  # satisfies the production password policy
        record = {k: user[k] for k in _USER_FIELDS if k in user}
        record["realmRoles"] = realm_roles
        record["credentials"] = [{"type": "password", "value": temp, "temporary": True}]
        record["requiredActions"] = ["UPDATE_PASSWORD", "CONFIGURE_TOTP"]
        out_users.append(record)
        passwords.append(f"{user['username']}\t{temp}")

    with _private(args.out) as fh:
        json.dump({"ifResourceExists": "SKIP", "users": out_users}, fh, indent=2)
    with _private(args.passwords_out) as fh:
        fh.write("\n".join(passwords) + "\n")
    print(f"Exported {len(out_users)} users to {args.out}; temporary passwords in {args.passwords_out}.")
    print("Both files are secrets: keep them off git and delete them after the import.")


def import_(args: argparse.Namespace) -> None:
    with open(args.file, encoding="utf-8") as fh:
        payload = json.load(fh)
    token = _token(args.target, args.admin_user, _admin_password())
    result = _call(args.target, token, "/partialImport", method="POST", payload=payload)
    print(json.dumps({k: result.get(k) for k in ("added", "skipped", "overwritten")}, indent=2))
    # Verify, don't assume: every exported id must now exist on the target.
    missing = []
    for user in payload["users"]:
        try:
            _call(args.target, token, f"/users/{user['id']}")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            missing.append(user["username"])
    if missing:
        sys.exit(f"Not present on the target after import: {', '.join(missing)}")
    print(f"All {len(payload['users'])} users present with their original ids.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export")
    exp.add_argument("--source", required=True, help="e.g. http://127.0.0.1:8081/auth")
    exp.add_argument("--admin-user", default="admin")
    exp.add_argument("--out", required=True)
    exp.add_argument("--passwords-out", required=True)
    exp.set_defaults(func=export)
    imp = sub.add_parser("import")
    imp.add_argument("--target", required=True, help="e.g. https://<temporary keycloak domain>/auth")
    imp.add_argument("--admin-user", default="admin")
    imp.add_argument("--file", required=True)
    imp.set_defaults(func=import_)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

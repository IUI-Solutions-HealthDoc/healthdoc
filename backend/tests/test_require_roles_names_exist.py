"""Every role a route allows is a role Keycloak can issue.

The radiology attachment routes allowed "radiologist", a role the realm does
not have, instead of radiology_tech, so the radiology technician got 403 on
every scan attachment (QA 12 Oct 2026). A misspelt role fails closed and
silently; this checks the names against the realm file.
"""
import ast
import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REALM = BACKEND.parent / "infra" / "keycloak" / "realm-healthdoc.json"

# Named beside a real role, so nobody is locked out; kept until the routes
# are reviewed. Do not add to this list to make a new route pass.
KNOWN_UNISSUED = {"registration", "pathologist"}


def _route_roles():
    for path in (BACKEND / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "require_roles":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        yield path.relative_to(BACKEND), arg.value


def test_every_required_role_exists_in_the_realm():
    realm = {role["name"] for role in json.loads(REALM.read_text())["roles"]["realm"]}
    unknown = sorted({(str(p), r) for p, r in _route_roles() if r not in realm | KNOWN_UNISSUED})
    assert unknown == []


def test_the_radiology_technician_can_reach_scan_attachments():
    source = (BACKEND / "app" / "radiology" / "router.py").read_text()
    allowed = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for deco in node.decorator_list:
            if not (isinstance(deco, ast.Call) and deco.args and isinstance(deco.args[0], ast.Constant)):
                continue
            if "attachments" not in str(deco.args[0].value):
                continue
            allowed[node.name] = {
                arg.value for call in ast.walk(deco)
                if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "require_roles"
                for arg in call.args if isinstance(arg, ast.Constant)
            }
    assert len(allowed) == 4
    assert all("radiology_tech" in roles for roles in allowed.values()), allowed

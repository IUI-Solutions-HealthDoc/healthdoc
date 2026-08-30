"""Role gates on the endpoints Track A found the UI hiding but the API granting.

WHY THIS FILE EXISTS

Manual Track A testing (Facility Admin bug report, 29 Aug 2026) found two
endpoints that returned 200 for `dev.admin` while the frontend redirected
admins away from the screens that call them:

    GET /queue/worklist                     -> 200 for admin
    GET /queue/hod-dashboard/{id}/...       -> 200 for admin

Both were `require_roles(<role>, "admin")`. Neither grant was used: the only
call sites are features/doctor and features/hod, and ROLES.ADMIN's route
prefixes are /admin, /billing, /reports and /audit-viewer. The permission
existed solely to be found.

The finding is worth more than the fix. **UI containment is not authorization.**
A hidden menu stops a confused user; it does nothing about a token and curl,
which is exactly what a CERT-In assessor uses. Any endpoint whose screen a role
cannot reach should refuse that role's token, and the two must be changed
together or not at all.

These tests read the mounted route table rather than making HTTP calls. That is
deliberate: it needs no database, runs in the container suite, and asserts the
property that actually regressed — the declared dependency — rather than one
observed response.
"""
from __future__ import annotations

import pytest

from app.main import app

#: (path fragment, roles that must NOT be granted)
#:
#: Expressed as a denial rather than an allow-list on purpose. An allow-list
#: fails whenever a legitimate role is added and trains people to update the
#: test without reading it; a denial only fails when a boundary genuinely moves.
FORBIDDEN = [
    ("/queue/worklist", {"admin", "auditor", "superadmin", "patient"}),
    ("/queue/hod-dashboard", {"admin", "auditor", "superadmin", "patient"}),
]


def _mounted_routes():
    """Every mounted route, on either of FastAPI's two routing models.

    Up to FastAPI 0.115 / Starlette 0.46, include_router() copied each APIRoute
    into app.routes, so a flat walk saw everything. FastAPI 0.141 / Starlette
    1.6 stopped flattening: each include_router() leaves ONE _IncludedRouter in
    app.routes and the real APIRoutes hang off its .original_router. Requests
    still resolve identically — only introspection changed — which is exactly
    why this surfaced as four red tests and zero broken endpoints, and why a
    flat walk reported "no mounted route matches '/queue/worklist'" for a route
    that was being served correctly at the time.

    Walking both shapes matters more than picking the current one: the host venv
    and CI were on opposite sides of that upgrade, so a version-specific walk
    passes for whoever runs it locally and fails for everyone else. Recursive
    because a router may include another router.
    """
    seen: set[int] = set()

    def walk(routes):
        for route in routes:
            if id(route) in seen:
                continue
            seen.add(id(route))
            yield route
            nested = getattr(route, "original_router", None)
            if nested is not None:
                yield from walk(getattr(nested, "routes", ()))

    return list(walk(app.routes))


def _roles_for(path_fragment: str) -> list[tuple[str, set[str]]]:
    """Every mounted route matching the fragment, with its required roles.

    Reads the roles out of the closure of the `require_roles(...)` dependency,
    because that is where the gate actually lives — a test that re-declares the
    expected roles in its own literal proves only that two lists match.
    """
    found = []
    for route in _mounted_routes():
        path = getattr(route, "path", "")
        if path_fragment not in path:
            continue
        roles: set[str] = set()
        for dep in getattr(route, "dependencies", []):
            call = getattr(dep, "dependency", None)
            closure = getattr(call, "__closure__", None) or ()
            for cell in closure:
                contents = cell.cell_contents
                if isinstance(contents, tuple) and all(isinstance(x, str) for x in contents):
                    roles.update(contents)
        found.append((path, roles))
    return found


@pytest.mark.parametrize("fragment, denied", FORBIDDEN)
def test_endpoint_does_not_grant_roles_the_ui_hides_it_from(fragment, denied):
    routes = _roles_for(fragment)
    assert routes, f"no mounted route matches {fragment!r} — did the path change?"

    for path, roles in routes:
        assert roles, f"{path} declares no require_roles dependency at all"
        leaked = roles & denied
        assert not leaked, (
            f"{path} grants {sorted(leaked)}. The frontend does not give those "
            f"roles a route to this screen, so the API must not accept their "
            f"tokens either — a hidden menu is not access control."
        )


def test_the_worklist_is_doctor_only():
    """Named separately because it is the one an assessor reproduces first."""
    routes = _roles_for("/queue/worklist")
    assert routes
    for path, roles in routes:
        assert roles == {"doctor"}, f"{path} expected exactly {{doctor}}, got {sorted(roles)}"


def test_every_hod_dashboard_endpoint_is_hod_only():
    """All five, not just the overview.

    The bug report reproduced it on the overview route. Narrowing only that one
    would leave four siblings open and the finding half-closed — the shape of
    fix that passes a retest and fails the next audit.
    """
    routes = _roles_for("/queue/hod-dashboard")
    assert len(routes) >= 5, f"expected at least 5 hod-dashboard routes, found {len(routes)}"
    for path, roles in routes:
        assert roles == {"hod"}, f"{path} expected exactly {{hod}}, got {sorted(roles)}"


def test_no_module_stub_is_publicly_reachable():
    """Every /ping is gated, and stays that way.

    WASA finding M4 gated five of these. Fourteen more were left public, and
    the ✅ beside M4 in docs/wasa-readiness.md read as though the finding were
    closed — so nothing was looking. Module enumeration stayed available to
    anyone who could reach the host for months afterwards.

    The payload is only {"module": …, "status": …}, so this was reconnaissance
    rather than data. It is still an unauthenticated endpoint on a hospital
    system, which is a finding on its own terms, and the cheapest moment to
    notice the next one is a failing test rather than an assessor's report.
    """
    def gate(route) -> set[str]:
        # _roles_for() above takes a path fragment; this needs one route's own
        # roles, so it reads the same closures directly.
        roles: set[str] = set()
        for dep in getattr(route, "dependencies", []):
            call = getattr(dep, "dependency", None)
            for cell in getattr(call, "__closure__", None) or ():
                contents = cell.cell_contents
                if isinstance(contents, tuple) and all(isinstance(x, str) for x in contents):
                    roles.update(contents)
        return roles

    unguarded = sorted(
        route.path
        for route in _mounted_routes()
        if getattr(route, "path", "").endswith("/ping") and not gate(route)
    )
    assert not unguarded, (
        "these module stubs answer without a role gate: " + ", ".join(unguarded)
    )

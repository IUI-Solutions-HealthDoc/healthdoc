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


def _roles_for(path_fragment: str) -> list[tuple[str, set[str]]]:
    """Every mounted route matching the fragment, with its required roles.

    Reads the roles out of the closure of the `require_roles(...)` dependency,
    because that is where the gate actually lives — a test that re-declares the
    expected roles in its own literal proves only that two lists match.
    """
    found = []
    for route in app.routes:
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

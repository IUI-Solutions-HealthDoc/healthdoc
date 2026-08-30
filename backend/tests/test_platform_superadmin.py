"""The platform workspace is useful without crossing into facility clinical data."""

import uuid

import pytest

from app.auth.deps import AuthUser
from app.platform.router import list_platform_facilities
from app.users.models import Facility

# Scoped to the one async test rather than the module. The route-table tests
# below are synchronous, and a module-level asyncio mark makes pytest-asyncio
# warn about every one of them.
@pytest.mark.asyncio
async def test_platform_lists_only_facility_metadata(db) -> None:
    facility = Facility(
        id=uuid.uuid4(),
        code=f"P{uuid.uuid4().hex[:5].upper()}",
        name="Platform Test Hospital",
        state_code="TS",
    )
    db.add(facility)
    await db.flush()

    result = await list_platform_facilities(
        _user=AuthUser(sub="platform-sub", roles=["superadmin"]),
        db=db,
        search="Platform Test",
        page=1,
        page_size=50,
    )

    assert result.total == 1
    assert result.items[0].id == facility.id

    # The EXACT field set, not a keyword scan.
    #
    # This previously read `assert "patient" not in model_dump()` and
    # `"clinical" not in model_dump()`, which a field called `patient_count` or
    # `primary_encounter_id` would sail straight past — the substring-instead-of-
    # structure mistake this repo has now made five times (see CLAUDE.md).
    #
    # Pinning the whole set means ANY new field on the platform response fails
    # this test and has to be justified against #464's contract, which is the
    # point: the isolation guarantee is about what superadmin can see, and a
    # field nobody argued for is exactly how that guarantee erodes.
    assert set(result.items[0].model_dump()) == {
        "id",
        "code",
        "name",
        "state_code",
        "district",
        "facility_type",
        "hfr_facility_id",
        "timezone",
        "is_active",
    }


# ---------------------------------------------------------------------------
# Tenant isolation (#464).
#
# The issue's acceptance criterion is "Superadmin has a dedicated workspace and
# never receives facility or clinical payloads." That is a statement about the
# whole mounted application, not about one endpoint, so these read the route
# table rather than calling handlers — a per-endpoint test cannot notice the
# route somebody adds next week.
#
# What these do NOT do is decide what the platform workspace should eventually
# expose. #464 is explicitly gated on a product/security decision about the
# cross-facility data contract, and inventing one here would be the wrong kind
# of progress. These pin the contract as it stands today so that widening it
# has to be deliberate.
# ---------------------------------------------------------------------------

from app.main import app  # noqa: E402


def _mounted_routes():
    """Every mounted route, on either of FastAPI's two routing models.

    Same walker as tests/test_role_boundaries.py, and the same reason: FastAPI
    0.141 / Starlette 1.6 stopped flattening included routers into app.routes,
    so a flat walk silently yields nothing and every assertion below would pass
    for the wrong reason.
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


def _roles_for(route) -> set[str]:
    """Roles required by a route, read out of the require_roles closure."""
    roles: set[str] = set()
    for dep in getattr(route, "dependencies", []):
        call = getattr(dep, "dependency", None)
        for cell in getattr(call, "__closure__", None) or ():
            contents = cell.cell_contents
            if isinstance(contents, tuple) and all(isinstance(x, str) for x in contents):
                roles.update(contents)
    return roles


def test_superadmin_is_granted_nowhere_outside_the_platform_workspace():
    """The isolation contract, stated as one assertion.

    A superadmin is a cloud operator with no facility. The moment any clinical
    or facility route adds "superadmin" to its require_roles — usually to make
    a support ticket easier — the role stops being data-isolated and #464's
    guarantee is gone, silently, because nothing else would notice.
    """
    leaked = sorted(
        route.path
        for route in _mounted_routes()
        if "superadmin" in _roles_for(route) and "/platform" not in getattr(route, "path", "")
    )
    assert not leaked, (
        "superadmin is granted on routes outside /platform: "
        + ", ".join(leaked)
        + ". A platform operator has no facility, so a facility-scoped handler "
        "cannot answer for them safely — see app/platform/router.py's docstring."
    )


def test_the_platform_workspace_admits_superadmin_and_nobody_else():
    """The other direction.

    Widening this to admit `admin` would hand one hospital's administrator a
    list of every other hospital on the deployment, which is the cross-facility
    disclosure the workspace exists to avoid.
    """
    platform_routes = [
        route for route in _mounted_routes()
        if "/platform" in getattr(route, "path", "") and _roles_for(route)
    ]
    assert platform_routes, "no /platform route carries a require_roles gate — did the path change?"

    for route in platform_routes:
        assert _roles_for(route) == {"superadmin"}, (
            f"{route.path} admits {sorted(_roles_for(route))}, expected exactly {{superadmin}}"
        )


def test_every_platform_route_is_gated():
    """An ungated /platform route would be reachable by any authenticated user.

    Checked separately from the test above because that one only looks at
    routes which already have a gate — an endpoint added with no dependencies
    at all would be invisible to it.
    """
    ungated = sorted(
        route.path
        for route in _mounted_routes()
        if getattr(route, "path", "").startswith("/api/v1/platform") and not _roles_for(route)
    )
    assert not ungated, f"/platform routes with no role gate: {', '.join(ungated)}"

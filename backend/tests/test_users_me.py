"""GET /users/me.

The endpoint the frontend needed and never had. Five feature modules had a
hardcoded `FACILITY_ID = MOCK_FACILITY_ID` standing in for it, and two admin
screens were putting that fake value in request bodies.

The ordering test below is the one that matters long-term. /users/me is only
reachable because it is registered before app.users.router's GET
/users/{user_id}; if that ordering is ever disturbed the endpoint fails 422 on
a UUID parse, which does not look like a routing problem to whoever hits it.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.users import me as me_router
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


class _Caller:
    def __init__(self, user_id: uuid.UUID, facility_id: uuid.UUID, roles: list[str]) -> None:
        self.id = user_id
        self.facility_id = facility_id
        self.roles = roles


async def _facility_and_user(db, roles: list[str]):
    facility = Facility(
        id=uuid.uuid4(), code=f"M{uuid.uuid4().hex[:4].upper()}",
        name="Ward Street Hospital", state_code="TS", timezone="Asia/Kolkata",
    )
    db.add(facility)
    await db.flush()

    user = User(
        id=uuid.uuid4(), keycloak_sub=f"sub-{uuid.uuid4().hex[:12]}",
        username=f"u{uuid.uuid4().hex[:8]}", full_name="Priya Nair",
        facility_id=facility.id,
    )
    db.add(user)
    await db.flush()
    return facility, user


async def test_me_returns_the_callers_own_identity_and_facility(db):
    facility, user = await _facility_and_user(db, ["receptionist"])

    result = await me_router.get_me(
        _Caller(user.id, facility.id, ["receptionist"]), db=db,
    )

    assert result.id == user.id
    assert result.username == user.username
    assert result.full_name == "Priya Nair"
    assert result.facility.id == facility.id
    assert result.facility.code == facility.code
    assert result.facility.name == "Ward Street Hospital"
    assert result.facility.timezone == "Asia/Kolkata"


async def test_roles_come_from_the_token_not_the_users_table(db):
    """The app's copy of a user's roles can lag a realm change until the next
    login, so the token is the authority."""
    facility, user = await _facility_and_user(db, ["doctor"])

    result = await me_router.get_me(
        _Caller(user.id, facility.id, ["doctor", "admin"]), db=db,
    )

    assert result.roles == ["doctor", "admin"]


async def test_me_carries_no_role_gate_so_every_role_can_read_it(db):
    """Deliberate: it can only ever return the caller's own record. Asserted so
    that nobody 'hardens' it later and silently breaks every non-admin screen —
    /users is otherwise an admin-only router."""
    facility, user = await _facility_and_user(db, ["nurse"])

    for roles in (["nurse"], ["pharmacist"], ["lab_tech"], ["receptionist"]):
        result = await me_router.get_me(_Caller(user.id, facility.id, roles), db=db)
        assert result.roles == roles


async def test_me_does_not_expose_contact_or_registration_detail(db):
    """Read by every screen for every role, so it stays narrow. Widening it is
    a deliberate act, not an accident of adding a column to the users table."""
    facility, user = await _facility_and_user(db, ["nurse"])

    result = await me_router.get_me(_Caller(user.id, facility.id, ["nurse"]), db=db)
    leaked = {"email", "mobile", "employee_id", "registration_number",
              "qualification", "keycloak_sub"} & set(result.model_dump().keys())
    assert not leaked, f"MeOut must not carry {leaked}"


async def test_a_deleted_account_gets_404_not_500(db):
    """get_current_db_user resolved the id from a still-valid token, so a miss
    means the row went away mid-session."""
    facility, _ = await _facility_and_user(db, ["nurse"])

    with pytest.raises(HTTPException) as caught:
        await me_router.get_me(_Caller(uuid.uuid4(), facility.id, ["nurse"]), db=db)

    assert caught.value.status_code == 404


async def test_users_me_is_registered_before_the_user_id_route():
    """The regression guard.

    Both /users/me and /users/{user_id} match the path "/users/me". FastAPI
    takes the first registered, so this asserts on the mounted application in
    the order main.py actually builds it — not on the routers in isolation,
    which is where the mistake would hide.

    Introspected via the OpenAPI schema rather than app.routes: this version
    keeps included routers as nested _IncludedRouter objects with no `.path`,
    so walking app.routes silently yields an empty list and the assertion
    passes for the wrong reason. The schema is built by iterating the routes in
    registration order, so its key order is the thing under test.
    """
    from app.main import app

    paths = list(app.openapi()["paths"].keys())

    assert "/api/v1/users/me" in paths, "GET /users/me is not mounted at all"
    assert "/api/v1/users/{user_id}" in paths, (
        "the admin route vanished — this guard is only meaningful with both present"
    )
    assert paths.index("/api/v1/users/me") < paths.index("/api/v1/users/{user_id}"), (
        "/users/me must be registered before /users/{user_id}, or 'me' is parsed "
        "as a UUID and the route 422s"
    )


# --- department, added for the HOD dashboard ---------------------------------
#
# The dashboard is per-department and the session had no way to say which
# department the caller belongs to. The alternative was a picker, and a picker
# would be wrong: the hod-dashboard endpoints are gated on role and scoped only
# to the caller's FACILITY, so a picker would let the head of Medicine read
# Surgery's workload and pending approvals.

async def _department(db, facility_id: uuid.UUID, name: str = "General Medicine"):
    from app.departments.models import Department

    department = Department(
        id=uuid.uuid4(), name=name, code=f"D{uuid.uuid4().hex[:4].upper()}",
        facility_id=facility_id,
    )
    db.add(department)
    await db.flush()
    return department


async def test_me_returns_the_callers_department(db):
    """What the HOD dashboard scopes itself by."""
    facility, user = await _facility_and_user(db, ["hod"])
    department = await _department(db, facility.id)
    user.department_id = department.id
    await db.flush()

    result = await me_router.get_me(_Caller(user.id, facility.id, ["hod"]), db=db)

    assert result.department is not None
    assert result.department.id == department.id
    assert result.department.name == "General Medicine"
    assert result.department.code == department.code


async def test_a_user_with_no_department_still_gets_a_response(db):
    """THE REASON THE JOIN IS OUTER.

    users.department_id is nullable — admin and auditor belong to no one
    department. An inner join would make /users/me return 404 for them, turning
    "has no department" into "has no account", on the endpoint every screen
    calls first. The whole app would fail to load for an admin.
    """
    facility, user = await _facility_and_user(db, ["admin"])

    result = await me_router.get_me(_Caller(user.id, facility.id, ["admin"]), db=db)

    assert result.department is None
    assert result.id == user.id, "the rest of the payload is unaffected"
    assert result.facility.id == facility.id


async def test_the_department_payload_stays_narrow(db):
    """MeOut's own docstring says it is deliberately narrow because every screen
    for every role reads it. The department is id, code, English name and an
    optional Hindi name — what a screen needs to scope and label itself — and
    nothing about its staff, rooms or configuration."""
    facility, user = await _facility_and_user(db, ["hod"])
    department = await _department(db, facility.id)
    user.department_id = department.id
    await db.flush()

    result = await me_router.get_me(_Caller(user.id, facility.id, ["hod"]), db=db)

    assert set(result.department.model_dump()) == {"id", "code", "name", "name_hi"}
    assert result.department.name_hi is None

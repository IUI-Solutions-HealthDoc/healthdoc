"""First-approver lookup for stock adjustments.

Regression for a defect that was invisible from the UI. The adjustment screen
searched for approvers through `GET /users`, which is gated `admin` at the
router, so a pharmacist got 403 on every keystroke — and the screen's
`.catch()` turned the refusal into an empty list. The role that owns
maker-checker adjustments was told, silently and wrongly, that no colleague by
that name works here.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text

from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.common.db import get_db
from app.main import app


def _client(db_session, *, user_id, facility_id, roles):
    auth_user = AuthUser(sub=f"cand-{user_id}", username=f"cand-{user_id}", roles=roles)
    db_user = DbUser(
        id=user_id,
        keycloak_sub=auth_user.sub,
        username=auth_user.username,
        facility_id=facility_id,
        roles=roles,
    )

    async def override_db():
        yield db_session

    app.dependency_overrides[get_current_user] = lambda: auth_user
    app.dependency_overrides[get_current_db_user] = lambda: db_user
    app.dependency_overrides[get_db] = override_db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_pharmacist_can_find_a_first_approver(db_session, pharmacy_seed):
    """The whole point: this is the call that used to 403."""
    try:
        async with _client(
            db_session,
            user_id=pharmacy_seed["pharmacist_id"],
            facility_id=pharmacy_seed["facility_id"],
            roles=["pharmacist"],
        ) as client:
            response = await client.get("/api/v1/pharmacy/adjustment-candidates")
            assert response.status_code == 200, response.text
            items = response.json()["data"]["items"]
            returned = {row["id"] for row in items}

            assert str(pharmacy_seed["doctor_id"]) in returned, (
                "A colleague at the same facility must be offerable as first approver"
            )
            # The database refuses created_by = first_approver_id, so offering
            # the submitter their own name is offering a choice that cannot work.
            assert str(pharmacy_seed["pharmacist_id"]) not in returned
            # A narrower contract than GET /users on purpose.
            assert set(items[0]) == {"id", "full_name", "designation"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_search_matches_a_partial_name(db_session, pharmacy_seed):
    # A second colleague who does NOT match the search term. Without this row
    # the seed leaves exactly one candidate, so an endpoint that ignored
    # `search` entirely would still return the expected single result and this
    # test would pass while checking nothing.
    decoy = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, keycloak_sub, username, full_name, facility_id)"
            " VALUES (:id, :sub, :username, 'Priya Nair', :facility_id)"
        ),
        {
            "id": decoy,
            "sub": f"decoy-{decoy}",
            "username": f"decoy-{uuid.uuid4().hex[:8]}",
            "facility_id": pharmacy_seed["facility_id"],
        },
    )
    await db_session.flush()

    try:
        async with _client(
            db_session,
            user_id=pharmacy_seed["pharmacist_id"],
            facility_id=pharmacy_seed["facility_id"],
            roles=["pharmacist"],
        ) as client:
            hit = await client.get("/api/v1/pharmacy/adjustment-candidates", params={"search": "octo"})
            assert hit.status_code == 200, hit.text
            assert [row["id"] for row in hit.json()["data"]["items"]] == [
                str(pharmacy_seed["doctor_id"])
            ]

            miss = await client.get(
                "/api/v1/pharmacy/adjustment-candidates", params={"search": "nobodyhere"}
            )
            assert miss.json()["data"]["items"] == []

            # And with no term at all, both colleagues are offered — proving the
            # single result above was the filter working, not an empty facility.
            everyone = await client.get("/api/v1/pharmacy/adjustment-candidates")
            assert {row["id"] for row in everyone.json()["data"]["items"]} == {
                str(pharmacy_seed["doctor_id"]),
                str(decoy),
            }
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_another_facilitys_staff_are_not_offered(db_session, pharmacy_seed):
    """Facility scope comes from the caller's row, never a query parameter."""
    other_facility = uuid.uuid4()
    outsider = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO facilities (id, code, name, state_code, timezone)"
            " VALUES (:id, :code, 'Other Facility', 'TS', 'Asia/Kolkata')"
        ),
        {"id": other_facility, "code": f"OTH{uuid.uuid4().hex[:8]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, keycloak_sub, username, full_name, facility_id)"
            " VALUES (:id, :sub, :username, 'Doctor Elsewhere', :facility_id)"
        ),
        {
            "id": outsider,
            "sub": f"outsider-{outsider}",
            "username": f"outsider-{uuid.uuid4().hex[:8]}",
            "facility_id": other_facility,
        },
    )
    await db_session.flush()

    try:
        async with _client(
            db_session,
            user_id=pharmacy_seed["pharmacist_id"],
            facility_id=pharmacy_seed["facility_id"],
            roles=["pharmacist"],
        ) as client:
            response = await client.get(
                "/api/v1/pharmacy/adjustment-candidates", params={"search": "Doctor"}
            )
            assert response.status_code == 200, response.text
            assert str(outsider) not in {row["id"] for row in response.json()["data"]["items"]}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["nurse", "receptionist", "auditor"])
async def test_roles_that_cannot_approve_cannot_browse_candidates(db_session, pharmacy_seed, role):
    """This endpoint is narrower than GET /users, not a way around its gate."""
    try:
        async with _client(
            db_session,
            user_id=pharmacy_seed["doctor_id"],
            facility_id=pharmacy_seed["facility_id"],
            roles=[role],
        ) as client:
            response = await client.get("/api/v1/pharmacy/adjustment-candidates")
            assert response.status_code == 403, response.text
    finally:
        app.dependency_overrides.clear()

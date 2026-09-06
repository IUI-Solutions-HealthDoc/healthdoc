"""Shift handover: the table shipped in 0050 with nothing able to write to it.

The frontend's AddHandoverForm and HandoverNotes were built against an API that
was never published, so a ward could not record the moment responsibility for a
patient transferred — and that is the first record any incident review asks
for.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text, update

from app.users.models import Facility, User

from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.common.db import get_db
from app.main import app


def _client(db, *, user_id, facility_id, roles):
    auth_user = AuthUser(sub=f"ho-{user_id}", username=f"ho-{user_id}", roles=roles)
    db_user = DbUser(
        id=user_id,
        keycloak_sub=auth_user.sub,
        username=auth_user.username,
        facility_id=facility_id,
        roles=roles,
    )

    async def override_db():
        yield db

    app.dependency_overrides[get_current_user] = lambda: auth_user
    app.dependency_overrides[get_current_db_user] = lambda: db_user
    app.dependency_overrides[get_db] = override_db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _body(admission_id, receiver_id, **over):
    payload = {
        "admission_id": str(admission_id),
        "shift": "night",
        "situation": "Post-operative day one, stable.",
        "background": "Admitted for elective procedure.",
        "assessment": "Vitals within range, pain controlled.",
        "recommendation": "Continue observations four-hourly.",
        "handed_over_to": str(receiver_id),
    }
    payload.update(over)
    return payload


@pytest.mark.asyncio
async def test_a_nurse_can_record_and_read_back_a_handover(db, nursing_seed):
    try:
        async with _client(
            db,
            user_id=nursing_seed["nurse_id"],
            facility_id=nursing_seed["facility_id"],
            roles=["nurse"],
        ) as client:
            created = await client.post(
                "/api/v1/nursing/handover-notes",
                json=_body(nursing_seed["admission_id"], nursing_seed["other_nurse_id"]),
            )
            assert created.status_code == 201, created.text
            note = created.json()["data"]
            assert note["shift"] == "night"
            assert note["handed_over_to"] == str(nursing_seed["other_nurse_id"])

            listed = await client.get(
                f"/api/v1/nursing/admissions/{nursing_seed['admission_id']}/handover-notes"
            )
            assert listed.status_code == 200, listed.text
            items = listed.json()["data"]["items"]
            assert [i["id"] for i in items] == [note["id"]]
            # Names resolved in the same query: the ward board renders a list
            # of these and a per-row user fetch is the N+1 to avoid.
            assert items[0]["handed_over_to_name"]
            assert items[0]["created_by_name"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_a_handover_to_yourself_is_refused(db, nursing_seed):
    """It looks like a handover in every report and transfers nothing."""
    try:
        async with _client(
            db,
            user_id=nursing_seed["nurse_id"],
            facility_id=nursing_seed["facility_id"],
            roles=["nurse"],
        ) as client:
            response = await client.post(
                "/api/v1/nursing/handover-notes",
                json=_body(nursing_seed["admission_id"], nursing_seed["nurse_id"]),
            )
            assert response.status_code == 422, response.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("receiver_state", ["inactive", "foreign", "missing"])
async def test_an_unusable_receiver_is_refused(db, nursing_seed, receiver_state):
    """The receiver is who accepted responsibility. It must be a real one."""
    receiver = nursing_seed["other_nurse_id"]
    # Through the ORM, not raw SQL: `users.id` is a UUID column and the SQLite
    # test engine will not bind a UUID to a textual comparison.
    if receiver_state == "inactive":
        await db.execute(update(User).where(User.id == receiver).values(is_active=False))
    elif receiver_state == "foreign":
        other = Facility(
            id=uuid.uuid4(), code=f"OTH{uuid.uuid4().hex[:8]}",
            name="Other Facility", state_code="DL",
        )
        db.add(other)
        await db.flush()
        await db.execute(update(User).where(User.id == receiver).values(facility_id=other.id))
    else:
        receiver = uuid.uuid4()
    await db.flush()

    try:
        async with _client(
            db,
            user_id=nursing_seed["nurse_id"],
            facility_id=nursing_seed["facility_id"],
            roles=["nurse"],
        ) as client:
            response = await client.post(
                "/api/v1/nursing/handover-notes",
                json=_body(nursing_seed["admission_id"], receiver),
            )
            # 404, never 403 — a 403 confirms the user exists elsewhere.
            assert response.status_code == 404, response.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_another_facilitys_admission_is_not_writable(db, nursing_seed):
    try:
        async with _client(
            db,
            user_id=nursing_seed["nurse_id"],
            facility_id=uuid.uuid4(),  # a nurse somewhere else entirely
            roles=["nurse"],
        ) as client:
            response = await client.post(
                "/api/v1/nursing/handover-notes",
                json=_body(nursing_seed["admission_id"], nursing_seed["other_nurse_id"]),
            )
            assert response.status_code == 404, response.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["receptionist", "pharmacist", "auditor"])
async def test_only_clinical_staff_may_sign_a_handover(db, nursing_seed, role):
    try:
        async with _client(
            db,
            user_id=nursing_seed["nurse_id"],
            facility_id=nursing_seed["facility_id"],
            roles=[role],
        ) as client:
            response = await client.post(
                "/api/v1/nursing/handover-notes",
                json=_body(nursing_seed["admission_id"], nursing_seed["other_nurse_id"]),
            )
            assert response.status_code == 403, response.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_every_sbar_field_is_required(db, nursing_seed):
    """The columns are nullable; the contract is not.

    A handover with the assessment left blank is the one nobody can act on.
    """
    try:
        async with _client(
            db,
            user_id=nursing_seed["nurse_id"],
            facility_id=nursing_seed["facility_id"],
            roles=["nurse"],
        ) as client:
            for field in ("situation", "background", "assessment", "recommendation"):
                body = _body(nursing_seed["admission_id"], nursing_seed["other_nurse_id"])
                del body[field]
                response = await client.post("/api/v1/nursing/handover-notes", json=body)
                assert response.status_code == 422, f"{field}: {response.text}"
    finally:
        app.dependency_overrides.clear()

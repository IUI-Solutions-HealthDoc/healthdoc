"""Regression tests for the authenticated critical-alert stream."""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.auth.deps import AuthUser, DbUser
from app.pathology import router as pathology_router


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "expected_key"),
    [
        ("doctor", lambda user: f"doctor:{user.id}"),
        ("lab_tech", lambda user: f"facility:{user.facility_id}:lab"),
    ],
)
async def test_stream_releases_identity_session_before_it_starts(
    monkeypatch, role, expected_key
):
    """An SSE connection must not reserve one DB-pool slot for its lifetime."""

    class ShortSession:
        exited = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            self.exited = True

    session = ShortSession()
    app_user = DbUser(
        id=uuid.uuid4(),
        keycloak_sub="doctor-sub",
        username="doctor",
        facility_id=uuid.uuid4(),
        roles=[role],
    )

    async def resolve_user(current_user, db):
        assert current_user.username == role
        assert db is session
        return app_user

    monkeypatch.setattr(pathology_router, "SessionLocal", lambda: session)
    monkeypatch.setattr(pathology_router, "get_current_db_user", resolve_user)

    response = await pathology_router.critical_alerts_stream(
        current_user=AuthUser(sub=f"{role}-sub", username=role, roles=[role])
    )

    assert session.exited, (
        "the identity lookup session is still open after the StreamingResponse "
        "was created; each doctor tab would permanently consume a pool slot"
    )

    iterator = response.body_iterator
    first_frame = await anext(iterator)
    assert first_frame == ": connected\n\n"
    assert expected_key(app_user) in pathology_router._critical_alert_subscribers
    await iterator.aclose()
    assert expected_key(app_user) not in pathology_router._critical_alert_subscribers


@pytest.mark.asyncio
@pytest.mark.parametrize("has_doctor", [True, False])
async def test_publish_reaches_lab_facility_even_without_an_ordering_doctor(
    monkeypatch, has_doctor
):
    facility_id = uuid.uuid4()
    doctor_id = uuid.uuid4() if has_doctor else None
    lab_queue = asyncio.Queue()
    doctor_queue = asyncio.Queue()
    pathology_router._critical_alert_subscribers.clear()
    pathology_router._critical_alert_subscribers[f"facility:{facility_id}:lab"] = [lab_queue]
    if doctor_id is not None:
        pathology_router._critical_alert_subscribers[f"doctor:{doctor_id}"] = [doctor_queue]

    async def resolve_doctor(db, item):
        return doctor_id

    monkeypatch.setattr(pathology_router, "_resolve_ordering_doctor_id", resolve_doctor)

    class FakeDb:
        def __init__(self):
            self.added = []

        async def get(self, model, key):
            return SimpleNamespace(facility_id=facility_id)

        def add(self, value):
            self.added.append(value)

        async def flush(self):
            return None

    item = SimpleNamespace(
        id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        accession_number="LAB-2099-000001",
    )
    try:
        await pathology_router._publish_critical_alert(FakeDb(), item, ["hemoglobin_g_dl"])

        assert not lab_queue.empty()
        if has_doctor:
            assert not doctor_queue.empty()
    finally:
        pathology_router._critical_alert_subscribers.clear()

"""Consent routes: actor attribution, retry keys and consent-manager decisions.

Real PostgreSQL through the actual router, because the properties under test
live in the wiring: which user id reaches the row, and whether a retried write
replays instead of running twice.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.deps import AuthUser, get_current_user
from app.common.db import get_db
from app.consent.router import router as consent_router

pytestmark = pytest.mark.asyncio


async def _sub_for(engine: AsyncEngine, user_id: uuid.UUID) -> str:
    async with engine.begin() as conn:
        return (
            await conn.execute(text("SELECT keycloak_sub FROM users WHERE id = :id"), {"id": user_id})
        ).scalar_one()


def _client(session_factory, sub: str, roles: list[str]) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(consent_router)

    async def _db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub=sub, username="tester", roles=roles)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _other_user(engine: AsyncEngine, facility_id: uuid.UUID) -> uuid.UUID:
    uid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (id, keycloak_sub, username, full_name, facility_id) "
                "VALUES (:id, :sub, :sub, 'Colleague', :facility_id)"
            ),
            {"id": uid, "sub": f"consent-test-{uid}", "facility_id": facility_id},
        )
    return uid


async def _consent_manager(engine: AsyncEngine) -> uuid.UUID:
    manager_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO consent_managers (id, cm_registration_id, name, is_active) "
                "VALUES (:id, :reg, 'Route Test Manager', true)"
            ),
            {"id": manager_id, "reg": f"CM-{uuid.uuid4().hex}"},
        )
    return manager_id


async def test_granted_by_is_the_caller_not_the_body(
    engine, session_factory, facility_id, user_id, patient_id, purpose_id
):
    colleague = await _other_user(engine, facility_id)
    async with _client(session_factory, await _sub_for(engine, user_id), ["receptionist"]) as client:
        response = await client.post(
            f"/consent/patients/{patient_id}/records",
            headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
            json={
                "purpose_id": str(purpose_id),
                "granted_by_type": "patient",
                "granted_by_user_id": str(colleague),
                "channel": "verbal",
            },
        )
    assert response.status_code == 201, response.text
    assert response.json()["granted_by_user_id"] == str(user_id)


async def test_withdrawal_is_attributed_to_the_caller_and_replays_on_retry(
    engine, session_factory, facility_id, user_id, patient_id, purpose_id
):
    colleague = await _other_user(engine, facility_id)
    sub = await _sub_for(engine, user_id)
    async with _client(session_factory, sub, ["receptionist"]) as client:
        created = await client.post(
            f"/consent/patients/{patient_id}/records",
            headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
            json={"purpose_id": str(purpose_id), "granted_by_type": "patient", "channel": "verbal"},
        )
        consent_id = created.json()["id"]
        body = {
            "withdrawn_by_type": "patient",
            "withdrawn_by_user_id": str(colleague),
            "reason": "patient asked",
        }

        missing_key = await client.post(f"/consent/records/{consent_id}/withdraw", json=body)
        key = {"Idempotency-Key": f"w-{uuid.uuid4()}"}
        first = await client.post(f"/consent/records/{consent_id}/withdraw", headers=key, json=body)
        retry = await client.post(f"/consent/records/{consent_id}/withdraw", headers=key, json=body)

    assert missing_key.status_code == 400
    assert first.status_code == 201, first.text
    assert first.json()["withdrawn_by_user_id"] == str(user_id)
    assert retry.status_code == 201
    assert retry.json()["id"] == first.json()["id"]
    async with engine.begin() as conn:
        count = (
            await conn.execute(
                text("SELECT count(*) FROM consent_withdrawals WHERE consent_id = :id"),
                {"id": consent_id},
            )
        ).scalar_one()
    assert count == 1


async def test_status_change_needs_a_key_and_a_decision_role(
    engine, session_factory, user_id, patient_id, purpose_id
):
    manager_id = await _consent_manager(engine)
    sub = await _sub_for(engine, user_id)
    async with _client(session_factory, sub, ["receptionist"]) as desk:
        created = await desk.post(
            f"/consent/patients/{patient_id}/records",
            headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
            json={
                "purpose_id": str(purpose_id),
                "granted_by_type": "patient",
                "channel": "abdm_consent_manager",
                "consent_manager_id": str(manager_id),
                "status": "requested",
            },
        )
        consent_id = created.json()["id"]
        missing_key = await desk.patch(
            f"/consent/records/{consent_id}/status", json={"status": "granted"}
        )
        desk_decision = await desk.patch(
            f"/consent/records/{consent_id}/status",
            headers={"Idempotency-Key": f"s-{uuid.uuid4()}"},
            json={"status": "granted"},
        )
    async with _client(session_factory, sub, ["doctor"]) as doctor:
        key = {"Idempotency-Key": f"s-{uuid.uuid4()}"}
        decided = await doctor.patch(
            f"/consent/records/{consent_id}/status", headers=key, json={"status": "granted"}
        )
        replayed = await doctor.patch(
            f"/consent/records/{consent_id}/status", headers=key, json={"status": "granted"}
        )

    assert created.status_code == 201, created.text
    assert missing_key.status_code == 400
    assert desk_decision.status_code == 403
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "granted"
    # Without the replay the second call would be a 409 "granted -> granted".
    assert replayed.status_code == 200
    assert replayed.json()["status_changed_at"] == decided.json()["status_changed_at"]

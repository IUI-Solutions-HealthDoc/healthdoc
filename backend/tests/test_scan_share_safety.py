"""Synthetic reception acceptance; never sends requests or identities to ABDM."""
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.auth.deps import AuthUser, DbUser, get_current_user, get_current_db_user
from app.common.db import get_db
from app.integrations.abdm.models import ScanShareTicket
from app.integrations.abdm.scan_share_router import router
from app.opd.models import Visit
from app.patients.models import Patient

pytestmark = pytest.mark.asyncio


async def fixture(db, seed):
    dept, _, user = seed
    patient = Patient(
        id=uuid.uuid4(), uhid="TEST-RECEPTION-ONLY", full_name="Synthetic Reception",
        sex="unknown", age_years=30, identity_path="demographics_only",
        facility_id=dept.facility_id, created_by=user.id,
    )
    db.add(patient)
    await db.flush()
    ticket = ScanShareTicket(
        id=uuid.uuid4(), facility_id=dept.facility_id, token_number="123",
        abha_address="synthetic@sbx", patient_id=patient.id, status="active",
        profile_data={"full_name": patient.full_name},
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db.add(ticket)
    await db.flush()
    caller = DbUser(id=user.id, keycloak_sub=user.keycloak_sub, username=user.username,
                    facility_id=dept.facility_id, roles=["receptionist"])
    app = FastAPI()
    app.include_router(router)
    async def session():
        yield db
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub=user.keycloak_sub, roles=caller.roles)
    app.dependency_overrides[get_current_db_user] = lambda: caller
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")
    return client, ticket, caller, patient


async def test_checkin_real_contract_stable_retry_and_counter_conflict(db, seed):
    client, ticket, _, patient = await fixture(db, seed)
    async with client:
        listed = await client.get("/abdm/scan-share/tickets?status=all")
        assert listed.status_code == 200
        assert isinstance(listed.json(), list)
        assert listed.json()[0]["patient_name"] == patient.full_name
        path = f"/abdm/scan-share/tickets/{ticket.id}/check-in"
        before = await db.scalar(select(func.count()).select_from(Visit))
        response = await client.post(path, json={"counter": " Desk A "})
        assert response.status_code == 200
        saved = response.json()
        assert saved["counter"] == "Desk A"
        assert saved["check_in_time"]
        assert saved["slip_barcode_data"] == str(ticket.id)
        assert ticket.abha_address not in saved["slip_barcode_data"]
        # Same operation can be recovered after expiry, without creating a new visit.
        ticket.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.flush()
        retry = await client.post(path, json={"counter": "Desk A"})
        assert retry.json() == saved
        assert (await client.post(path, json={"counter": "Desk B"})).status_code == 409
        detail = (await client.get(f"/abdm/scan-share/tickets/{ticket.id}")).json()
        assert detail["status"] == "checked_in"
        assert detail["checked_in_at"] == saved["check_in_time"]
        assert await db.scalar(select(func.count()).select_from(Visit)) == before


@pytest.mark.parametrize("state", ["time_expired", "expired", "cancelled"])
async def test_expired_or_inactive_ticket_cannot_check_in(db, seed, state):
    client, ticket, _, _ = await fixture(db, seed)
    if state == "time_expired":
        ticket.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        ticket.status = state
    await db.flush()
    async with client:
        response = await client.post(f"/abdm/scan-share/tickets/{ticket.id}/check-in", json={"counter": "A"})
        assert response.status_code == 409
        assert ticket.checked_in_at is None
        active = (await client.get("/abdm/scan-share/tickets?status=active")).json()
        assert active == []
        if state != "cancelled":
            expired = (await client.get("/abdm/scan-share/tickets?status=expired")).json()
            assert expired[0]["status"] == "expired"


async def test_reused_human_token_is_ambiguous_but_uuid_selects_exact_ticket(db, seed):
    client, ticket, _, _ = await fixture(db, seed)
    duplicate = ScanShareTicket(
        id=uuid.uuid4(), facility_id=ticket.facility_id, token_number=ticket.token_number,
        abha_address="another-synthetic@sbx", profile_data={}, status="active",
        expires_at=ticket.expires_at,
    )
    db.add(duplicate)
    await db.flush()
    async with client:
        path = f"/abdm/scan-share/tickets/{ticket.token_number}"
        assert (await client.get(path)).status_code == 409
        assert (await client.post(path + "/check-in", json={"counter": "A"})).status_code == 409
        assert ticket.status == duplicate.status == "active"
        assert (await client.post(f"/abdm/scan-share/tickets/{ticket.id}/check-in", json={"counter": "A"})).status_code == 200
        assert duplicate.status == "active"


@pytest.mark.parametrize("payload", [{}, {"counter": "  "}, {"counter": "A\nB"}, {"counter": "a" * 51},
                                     {"counter_id": "A"}, {"counter": "A", "department_id": str(uuid.uuid4())}])
async def test_wrong_or_ignored_fields_are_rejected(db, seed, payload):
    client, ticket, _, _ = await fixture(db, seed)
    async with client:
        response = await client.post(f"/abdm/scan-share/tickets/{ticket.id}/check-in", json=payload)
        assert response.status_code == 422
        assert ticket.status == "active"


async def test_cross_facility_and_deleted_patient_are_not_returned_or_changed(db, seed):
    client, ticket, caller, patient = await fixture(db, seed)
    facility_id = caller.facility_id
    async with client:
        caller.facility_id = uuid.uuid4()
        assert (await client.get("/abdm/scan-share/tickets")).json() == []
        assert (await client.get(f"/abdm/scan-share/tickets/{ticket.id}")).status_code == 404
        assert (await client.post(f"/abdm/scan-share/tickets/{ticket.id}/check-in", json={"counter": "A"})).status_code == 404
        caller.facility_id = facility_id
        patient.deleted_at = datetime.now(UTC)
        await db.flush()
        assert (await client.get("/abdm/scan-share/tickets")).json() == []
        assert (await client.get(f"/abdm/scan-share/tickets/{ticket.id}")).status_code == 404
        assert ticket.status == "active"


@pytest.mark.parametrize("roles", [["doctor"], ["patient"], ["auditor"], ["patient", "receptionist"]])
async def test_unauthorized_or_unbound_mixed_role_cannot_read_ticket(db, seed, roles):
    client, ticket, caller, _ = await fixture(db, seed)
    caller.roles = roles
    ticket.patient_id = None  # Unbound shared profiles still contain protected demographics.
    await db.flush()
    async with client:
        response = await client.get(f"/abdm/scan-share/tickets/{ticket.id}")
        assert response.status_code in (403, 404)

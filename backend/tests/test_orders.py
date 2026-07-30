"""Tests for app/orders/router.py order creation + status transitions (#181, B3-W3-02)."""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.week3


@pytest.fixture
async def seeded_encounter_for_order(db_session, fake_facility):
    from app.patients.models import Patient
    from app.opd.models import Visit, Encounter
    from app.users.models import User

    doctor = User(
        keycloak_sub="order-doctor-sub",
        username="order.doctor",
        full_name="Order Doctor",
        facility_id=fake_facility.id,
    )
    db_session.add(doctor)
    await db_session.flush()

    patient = Patient(
        full_name="Order Test Patient",
        sex="male",
        age_years=52,
        identity_path="demographics_only",
        facility_id=fake_facility.id,
        created_by=doctor.id,
    )
    db_session.add(patient)
    await db_session.flush()

    visit = Visit(
        visit_number=f"VST-ORD-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        facility_id=fake_facility.id,
        visit_type="opd",
        status="in_consultation",
        visit_date=datetime(2026, 7, 25, 9, 0, 0, tzinfo=timezone.utc),
        created_by=doctor.id,
    )
    db_session.add(visit)
    await db_session.flush()

    encounter = Encounter(
        visit_id=visit.id,
        provider_user_id=doctor.id,
        created_by=doctor.id,
    )
    db_session.add(encounter)
    await db_session.flush()

    return {"doctor": doctor, "patient": patient, "encounter": encounter}


async def _create_order(authed_client, seed, order_type="lab", priority="routine"):
    payload = {
        "encounter_id": str(seed["encounter"].id),
        "patient_id": str(seed["patient"].id),
        "created_by": str(seed["doctor"].id),
        "order_type": order_type,
        "priority": priority,
    }
    return await authed_client.post("/api/v1/orders", json=payload)


async def test_create_order_generates_order_number(
    authed_client: AsyncClient, seeded_encounter_for_order
):
    seed = seeded_encounter_for_order
    response = await _create_order(authed_client, seed)
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["order_number"]
    assert body["order_type"] == "lab"
    assert body["status"] == "placed"


async def test_two_orders_get_distinct_order_numbers(
    authed_client: AsyncClient, seeded_encounter_for_order
):
    seed = seeded_encounter_for_order
    r1 = await _create_order(authed_client, seed)
    r2 = await _create_order(authed_client, seed)
    assert r1.json()["data"]["order_number"] != r2.json()["data"]["order_number"]


async def test_list_orders_filters_by_patient(
    authed_client: AsyncClient, seeded_encounter_for_order
):
    seed = seeded_encounter_for_order
    await _create_order(authed_client, seed)

    response = await authed_client.get(
        "/api/v1/orders", params={"patient_id": str(seed["patient"].id)}
    )
    assert response.status_code == 200
    items = response.json()["data"]
    assert len(items) >= 1
    assert all(item["patient_id"] == str(seed["patient"].id) for item in items)


async def test_get_order_not_found_returns_404(authed_client: AsyncClient):
    response = await authed_client.get(f"/api/v1/orders/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_allowed_status_transition_succeeds(
    authed_client: AsyncClient, seeded_encounter_for_order
):
    seed = seeded_encounter_for_order
    create_resp = await _create_order(authed_client, seed)
    order_id = create_resp.json()["data"]["id"]

    response = await authed_client.patch(f"/api/v1/orders/{order_id}", json={"status": "accepted"})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "accepted"


async def test_illegal_status_transition_returns_409(
    authed_client: AsyncClient, seeded_encounter_for_order
):
    seed = seeded_encounter_for_order
    create_resp = await _create_order(authed_client, seed)
    order_id = create_resp.json()["data"]["id"]

    # placed -> completed is not in the allowed-transitions map.
    response = await authed_client.patch(f"/api/v1/orders/{order_id}", json={"status": "completed"})
    assert response.status_code == 409


async def test_terminal_status_has_no_further_transitions(
    authed_client: AsyncClient, seeded_encounter_for_order
):
    seed = seeded_encounter_for_order
    create_resp = await _create_order(authed_client, seed)
    order_id = create_resp.json()["data"]["id"]

    await authed_client.patch(f"/api/v1/orders/{order_id}", json={"status": "cancelled"})
    response = await authed_client.patch(f"/api/v1/orders/{order_id}", json={"status": "accepted"})
    assert response.status_code == 409

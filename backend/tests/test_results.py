"""Tests for app/orders/results_router.py (#200, B3-W4-01).

NOTE: this router has no authentication dependency and takes
created_by/performed_by/reviewed_by directly from the request body
rather than the authenticated user (unlike app/admissions/service.py,
which resolves the user from the JWT). Tests below reflect the code
as written -- this is flagged for the team, not silently patched here.
"""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.week4


@pytest.fixture
async def seeded_order(db_session, fake_facility):
    from app.patients.models import Patient
    from app.opd.models import Visit, Encounter
    from app.orders.models import Order
    from app.users.models import User

    doctor = User(
        keycloak_sub="results-doctor-sub",
        username="results.doctor",
        full_name="Results Doctor",
        facility_id=fake_facility.id,
    )
    db_session.add(doctor)
    await db_session.flush()

    patient = Patient(
        full_name="Results Test Patient",
        sex="female",
        age_years=40,
        identity_path="demographics_only",
        facility_id=fake_facility.id,
        created_by=doctor.id,
    )
    db_session.add(patient)
    await db_session.flush()

    visit = Visit(
        visit_number=f"VST-RES-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        facility_id=fake_facility.id,
        visit_type="opd",
        status="registered",
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

    order = Order(
        order_number=f"ORD-{uuid.uuid4().hex[:8]}",
        encounter_id=encounter.id,
        patient_id=patient.id,
        order_type="lab",
        ordered_at=datetime(2026, 7, 25, 9, 5, 0, tzinfo=timezone.utc),
        created_by=doctor.id,
    )
    db_session.add(order)
    await db_session.flush()

    return {"doctor": doctor, "patient": patient, "order": order}


async def test_create_result_succeeds(authed_client: AsyncClient, seeded_order):
    seed = seeded_order
    payload = {
        "order_id": str(seed["order"].id),
        "created_by": str(seed["doctor"].id),
        "result_status": "preliminary",
        "result_text": "Hemoglobin 13.2 g/dL",
    }
    response = await authed_client.post("/api/v1/results", json=payload)
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["order_id"] == str(seed["order"].id)
    assert body["result_status"] == "preliminary"
    assert body["result_text"] == "Hemoglobin 13.2 g/dL"
    assert body["is_signed_off"] is False


async def test_list_results_filters_by_order(authed_client: AsyncClient, seeded_order):
    seed = seeded_order
    payload = {
        "order_id": str(seed["order"].id),
        "created_by": str(seed["doctor"].id),
        "result_status": "final",
    }
    await authed_client.post("/api/v1/results", json=payload)

    response = await authed_client.get(
        "/api/v1/results", params={"order_id": str(seed["order"].id)}
    )
    assert response.status_code == 200
    items = response.json()["data"]
    assert len(items) >= 1
    assert all(item["order_id"] == str(seed["order"].id) for item in items)


async def test_get_result_not_found_returns_404(authed_client: AsyncClient):
    response = await authed_client.get(f"/api/v1/results/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_review_result_sets_signoff_fields(authed_client: AsyncClient, seeded_order):
    seed = seeded_order
    create_payload = {
        "order_id": str(seed["order"].id),
        "created_by": str(seed["doctor"].id),
        "result_status": "preliminary",
        "result_text": "Initial reading",
    }
    create_resp = await authed_client.post("/api/v1/results", json=create_payload)
    result_id = create_resp.json()["data"]["id"]

    review_payload = {
        "reviewed_by": str(seed["doctor"].id),
        "review_notes": "Confirmed, matches clinical picture",
        "result_status": "final",
        "is_signed_off": True,
    }
    response = await authed_client.patch(f"/api/v1/results/{result_id}/review", json=review_payload)
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["reviewed_by"] == str(seed["doctor"].id)
    assert body["review_notes"] == "Confirmed, matches clinical picture"
    assert body["result_status"] == "final"
    assert body["is_signed_off"] is True
    assert body["reviewed_at"] is not None


async def test_review_nonexistent_result_returns_404(authed_client: AsyncClient, seeded_order):
    seed = seeded_order
    payload = {"reviewed_by": str(seed["doctor"].id)}
    response = await authed_client.patch(f"/api/v1/results/{uuid.uuid4()}/review", json=payload)
    assert response.status_code == 404

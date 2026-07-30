"""Tests for app/queue/router.py doctor queue (#180, B3-W3-01)."""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.week3


@pytest.fixture
async def seeded_queue_data(db_session, fake_facility):
    from app.patients.models import Patient
    from app.opd.models import Visit, Encounter
    from app.users.models import User

    doctor_a = User(
        keycloak_sub="queue-doctor-a-sub",
        username="queue.doctor.a",
        full_name="Queue Doctor A",
        facility_id=fake_facility.id,
    )
    doctor_b = User(
        keycloak_sub="queue-doctor-b-sub",
        username="queue.doctor.b",
        full_name="Queue Doctor B",
        facility_id=fake_facility.id,
    )
    db_session.add_all([doctor_a, doctor_b])
    await db_session.flush()

    patient = Patient(
        full_name="Queue Test Patient",
        sex="male",
        age_years=33,
        identity_path="demographics_only",
        facility_id=fake_facility.id,
        created_by=doctor_a.id,
    )
    db_session.add(patient)
    await db_session.flush()

    # Waiting visit -- registered, no encounter yet.
    waiting_visit = Visit(
        visit_number=f"VST-Q-WAIT-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        facility_id=fake_facility.id,
        visit_type="opd",
        status="registered",
        visit_date=datetime(2026, 7, 25, 8, 0, 0, tzinfo=timezone.utc),
        created_by=doctor_a.id,
    )
    # In-progress visit -- has an open encounter with doctor_a.
    active_visit = Visit(
        visit_number=f"VST-Q-ACTIVE-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        facility_id=fake_facility.id,
        visit_type="opd",
        status="in_consultation",
        visit_date=datetime(2026, 7, 25, 8, 30, 0, tzinfo=timezone.utc),
        created_by=doctor_a.id,
    )
    # Completed visit -- should never appear in the queue.
    completed_visit = Visit(
        visit_number=f"VST-Q-DONE-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        facility_id=fake_facility.id,
        visit_type="opd",
        status="completed",
        visit_date=datetime(2026, 7, 25, 7, 0, 0, tzinfo=timezone.utc),
        created_by=doctor_a.id,
    )
    db_session.add_all([waiting_visit, active_visit, completed_visit])
    await db_session.flush()

    active_encounter = Encounter(
        visit_id=active_visit.id,
        provider_user_id=doctor_a.id,
        created_by=doctor_a.id,
    )
    db_session.add(active_encounter)
    await db_session.flush()

    return {
        "doctor_a": doctor_a,
        "doctor_b": doctor_b,
        "patient": patient,
        "waiting_visit": waiting_visit,
        "active_visit": active_visit,
        "completed_visit": completed_visit,
    }


async def test_queue_excludes_completed_visits(authed_client: AsyncClient, seeded_queue_data):
    seed = seeded_queue_data
    response = await authed_client.get("/api/v1/queue")
    assert response.status_code == 200
    visit_ids = {item["visit_id"] for item in response.json()["data"]}
    assert str(seed["waiting_visit"].id) in visit_ids
    assert str(seed["active_visit"].id) in visit_ids
    assert str(seed["completed_visit"].id) not in visit_ids


async def test_queue_includes_patient_name_and_uhid(authed_client: AsyncClient, seeded_queue_data):
    seed = seeded_queue_data
    response = await authed_client.get("/api/v1/queue")
    items = response.json()["data"]
    entry = next(i for i in items if i["visit_id"] == str(seed["waiting_visit"].id))
    assert entry["patient_name"] == "Queue Test Patient"


async def test_queue_filters_by_provider_shows_own_and_unassigned(
    authed_client: AsyncClient, seeded_queue_data
):
    seed = seeded_queue_data
    response = await authed_client.get(
        "/api/v1/queue", params={"provider_user_id": str(seed["doctor_a"].id)}
    )
    visit_ids = {item["visit_id"] for item in response.json()["data"]}
    # doctor_a's own active encounter + the unassigned waiting visit
    assert str(seed["active_visit"].id) in visit_ids
    assert str(seed["waiting_visit"].id) in visit_ids


async def test_queue_filters_by_provider_excludes_other_doctors_encounters(
    authed_client: AsyncClient, seeded_queue_data
):
    seed = seeded_queue_data
    response = await authed_client.get(
        "/api/v1/queue", params={"provider_user_id": str(seed["doctor_b"].id)}
    )
    visit_ids = {item["visit_id"] for item in response.json()["data"]}
    # doctor_b has no encounters -- active_visit belongs to doctor_a, must be excluded.
    assert str(seed["active_visit"].id) not in visit_ids
    # unassigned waiting visit still shows for any provider.
    assert str(seed["waiting_visit"].id) in visit_ids

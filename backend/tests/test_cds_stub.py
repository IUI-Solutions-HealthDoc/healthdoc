"""Tests for #229 (B3-W6-01): CDS stub -- rule-based interaction flag
+ allergy check on prescription save.
"""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.week6


@pytest.fixture
async def seeded_encounter_for_cds(db_session, fake_facility):
    from app.patients.models import Patient
    from app.opd.models import Visit, Encounter
    from app.users.models import User

    doctor = User(
        keycloak_sub="cds-doctor-sub",
        username="cds.doctor",
        full_name="CDS Doctor",
        facility_id=fake_facility.id,
    )
    db_session.add(doctor)
    await db_session.flush()

    patient = Patient(
        full_name="CDS Test Patient",
        sex="female",
        age_years=55,
        identity_path="demographics_only",
        facility_id=fake_facility.id,
        created_by=doctor.id,
    )
    db_session.add(patient)
    await db_session.flush()

    visit = Visit(
        visit_number=f"VST-CDS-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        facility_id=fake_facility.id,
        visit_type="opd",
        status="in_consultation",
        visit_date=datetime(2026, 7, 30, 9, 0, 0, tzinfo=timezone.utc),
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


async def test_create_allergy_succeeds_and_is_audited(
    authed_client: AsyncClient, seeded_encounter_for_cds, db_session
):
    seed = seeded_encounter_for_cds
    payload = {
        "allergen": "Penicillin",
        "reaction": "Rash",
        "severity": "moderate",
        "created_by": str(seed["doctor"].id),
    }
    response = await authed_client.post(
        f"/api/v1/patients/{seed['patient'].id}/allergies", json=payload
    )
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["allergen"] == "Penicillin"
    assert body["severity"] == "moderate"

    from sqlalchemy import select
    from app.audit.models import AuditLog
    stmt = select(AuditLog).where(
        AuditLog.resource_id == uuid.UUID(body["id"]), AuditLog.action == "patient_allergy.create"
    )
    result = await db_session.execute(stmt)
    audit_entry = result.scalar_one()
    assert audit_entry.patient_id == seed["patient"].id


async def test_list_allergies_returns_recorded_allergy(
    authed_client: AsyncClient, seeded_encounter_for_cds
):
    seed = seeded_encounter_for_cds
    payload = {"allergen": "Sulfa drugs", "created_by": str(seed["doctor"].id)}
    await authed_client.post(f"/api/v1/patients/{seed['patient'].id}/allergies", json=payload)

    response = await authed_client.get(f"/api/v1/patients/{seed['patient'].id}/allergies")
    assert response.status_code == 200
    items = response.json()["data"]
    assert any(a["allergen"] == "Sulfa drugs" for a in items)


async def test_prescription_flags_known_drug_interaction(
    authed_client: AsyncClient, seeded_encounter_for_cds
):
    seed = seeded_encounter_for_cds
    payload = {
        "encounter_id": str(seed["encounter"].id),
        "patient_id": str(seed["patient"].id),
        "created_by": str(seed["doctor"].id),
        "items": [
            {"medicine_name": "Warfarin", "dosage": "5mg"},
            {"medicine_name": "Aspirin", "dosage": "75mg"},
        ],
    }
    response = await authed_client.post("/api/v1/prescriptions", json=payload)
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["items"]  # prescription still saves despite the flag
    interaction_flags = [f for f in body["cds_flags"] if f["type"] == "interaction"]
    assert len(interaction_flags) == 1
    assert "Warfarin" in interaction_flags[0]["drug_a"] or "Warfarin" in interaction_flags[0]["drug_b"]


async def test_prescription_flags_recorded_allergy(
    authed_client: AsyncClient, seeded_encounter_for_cds
):
    seed = seeded_encounter_for_cds
    await authed_client.post(
        f"/api/v1/patients/{seed['patient'].id}/allergies",
        json={"allergen": "Amoxicillin", "created_by": str(seed["doctor"].id)},
    )

    payload = {
        "encounter_id": str(seed["encounter"].id),
        "patient_id": str(seed["patient"].id),
        "created_by": str(seed["doctor"].id),
        "items": [{"medicine_name": "Amoxicillin", "dosage": "500mg"}],
    }
    response = await authed_client.post("/api/v1/prescriptions", json=payload)
    assert response.status_code == 201
    body = response.json()["data"]
    allergy_flags = [f for f in body["cds_flags"] if f["type"] == "allergy"]
    assert len(allergy_flags) == 1
    assert allergy_flags[0]["allergen"] == "Amoxicillin"


async def test_prescription_without_flags_has_empty_cds_flags(
    authed_client: AsyncClient, seeded_encounter_for_cds
):
    seed = seeded_encounter_for_cds
    payload = {
        "encounter_id": str(seed["encounter"].id),
        "patient_id": str(seed["patient"].id),
        "created_by": str(seed["doctor"].id),
        "items": [{"medicine_name": "Paracetamol", "dosage": "500mg"}],
    }
    response = await authed_client.post("/api/v1/prescriptions", json=payload)
    assert response.status_code == 201
    assert response.json()["data"]["cds_flags"] == []

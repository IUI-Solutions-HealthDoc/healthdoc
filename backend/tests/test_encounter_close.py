"""Tests for app/encounters/close_router.py (#201, B3-W4-02).

close_router.py calls app.common.mongo.get_mongo() directly (a plain
module-level function, not a FastAPI dependency), so it can't be
swapped via app.dependency_overrides the way get_db/get_current_user
are. These tests monkeypatch get_mongo() at the point close_router.py
imported it, with an in-memory fake collection -- this verifies the
real business logic (FHIR resource building, the 409 double-close
guard, encounter state changes) without needing a live Mongo instance.
"""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.week4


class _FakeInsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class _FakeCollection:
    def __init__(self):
        self.inserted_docs = []

    async def insert_one(self, doc):
        self.inserted_docs.append(doc)
        return _FakeInsertResult(f"fake-id-{len(self.inserted_docs)}")


class _FakeMongoDB:
    def __init__(self):
        self.fhir_bundles = _FakeCollection()

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.fixture
def fake_mongo(monkeypatch):
    fake_db = _FakeMongoDB()
    monkeypatch.setattr("app.encounters.close_router.get_mongo", lambda: fake_db)
    return fake_db


@pytest.fixture
async def seeded_encounter(db_session, fake_facility):
    from app.patients.models import Patient
    from app.opd.models import Visit, Encounter
    from app.users.models import User

    doctor = User(
        keycloak_sub="close-doctor-sub",
        username="close.doctor",
        full_name="Close Doctor",
        facility_id=fake_facility.id,
    )
    db_session.add(doctor)
    await db_session.flush()

    patient = Patient(
        full_name="Close Test Patient",
        sex="male",
        age_years=35,
        identity_path="demographics_only",
        facility_id=fake_facility.id,
        created_by=doctor.id,
    )
    db_session.add(patient)
    await db_session.flush()

    visit = Visit(
        visit_number=f"VST-CLOSE-{uuid.uuid4().hex[:8]}",
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
        subjective="Cough for 3 days",
        objective="Clear chest on auscultation",
        assessment="Viral URI",
        plan="Symptomatic treatment",
    )
    db_session.add(encounter)
    await db_session.flush()

    return {"doctor": doctor, "patient": patient, "visit": visit, "encounter": encounter}


async def test_close_encounter_without_prescription_succeeds(
    authed_client: AsyncClient, seeded_encounter, fake_mongo, db_session
):
    seed = seeded_encounter
    response = await authed_client.post(f"/api/v1/encounters/{seed['encounter'].id}/close")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["ended_at"] is not None
    assert body["fhir_bundle_id"] is not None

    assert len(fake_mongo.fhir_bundles.inserted_docs) == 1
    doc = fake_mongo.fhir_bundles.inserted_docs[0]
    assert doc["encounter_id"] == str(seed["encounter"].id)
    assert doc["patient_id"] == str(seed["patient"].id)
    # Only the OPD note Composition -- no prescriptions on this encounter.
    assert len(doc["resources"]) == 1


async def test_close_encounter_with_prescription_builds_medication_requests(
    authed_client: AsyncClient, seeded_encounter, fake_mongo, db_session
):
    from app.orders.models import Prescription, PrescriptionItem

    seed = seeded_encounter
    prescription = Prescription(
        encounter_id=seed["encounter"].id,
        patient_id=seed["patient"].id,
        created_by=seed["doctor"].id,
    )
    db_session.add(prescription)
    await db_session.flush()

    item1 = PrescriptionItem(
        prescription_id=prescription.id,
        medicine_name="Paracetamol",
        dosage="500mg",
        frequency="TID",
        duration_days=5,
        route="oral",
    )
    item2 = PrescriptionItem(
        prescription_id=prescription.id,
        medicine_name="Cetirizine",
        dosage="10mg",
        frequency="OD",
        duration_days=5,
        route="oral",
    )
    db_session.add_all([item1, item2])
    await db_session.flush()

    response = await authed_client.post(f"/api/v1/encounters/{seed['encounter'].id}/close")
    assert response.status_code == 200

    doc = fake_mongo.fhir_bundles.inserted_docs[0]
    # 1 Composition + 2 MedicationRequests
    assert len(doc["resources"]) == 3


async def test_close_encounter_twice_returns_409(
    authed_client: AsyncClient, seeded_encounter, fake_mongo
):
    seed = seeded_encounter
    first = await authed_client.post(f"/api/v1/encounters/{seed['encounter'].id}/close")
    assert first.status_code == 200

    second = await authed_client.post(f"/api/v1/encounters/{seed['encounter'].id}/close")
    assert second.status_code == 409


async def test_close_nonexistent_encounter_returns_404(authed_client: AsyncClient, fake_mongo):
    response = await authed_client.post(f"/api/v1/encounters/{uuid.uuid4()}/close")
    assert response.status_code == 404

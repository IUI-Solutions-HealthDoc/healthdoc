"""
Service-layer tests for app.orders.service -- create_prescription,
get_prescription, get_prescription_items. No CDS check yet (allergy/
interaction wiring lands in a follow-up PR stacked on this one) --
these tests cover the plain save path only.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.orders import service
from app.orders.models import PrescriptionItem
from app.orders.schemas import PrescriptionCreate, PrescriptionItemCreate

pytestmark = pytest.mark.asyncio


class TestCreatePrescription:
    async def test_create_saves_header_and_items(self, db, seed, encounter):
        _dept, _room, doctor = seed
        payload = PrescriptionCreate(
            encounter_id=encounter.id,
            notes="Take with food",
            items=[
                PrescriptionItemCreate(
                    medicine_name="Amoxicillin", dosage="500mg", frequency="tds",
                    duration_days=5, route="oral",
                ),
                PrescriptionItemCreate(medicine_name="Paracetamol", dosage="650mg", frequency="qid"),
            ],
        )
        prescription, _warnings = await service.create_prescription(db, payload, created_by=doctor.id)

        assert prescription.encounter_id == encounter.id
        assert prescription.facility_id == encounter.facility_id
        assert prescription.notes == "Take with food"

        items = await service.get_prescription_items(db, prescription.id)
        assert len(items) == 2
        names = {i.medicine_name for i in items}
        assert names == {"Amoxicillin", "Paracetamol"}
        for item in items:
            assert item.status == "prescribed"
            assert item.allergy_override_reason is None
            assert item.allergy_override_by is None

    async def test_create_resolves_patient_id_via_encounter_then_visit(self, db, seed, encounter, visit):
        """Encounter has no patient_id of its own -- create_prescription
        must resolve it via encounter.visit_id -> visit.patient_id."""
        _dept, _room, doctor = seed
        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(medicine_name="Ibuprofen"),
        ])
        prescription, _warnings = await service.create_prescription(db, payload, created_by=doctor.id)
        assert prescription.patient_id == visit.patient_id

    async def test_create_with_nonexistent_encounter_raises(self, db, seed):
        _dept, _room, doctor = seed
        payload = PrescriptionCreate(encounter_id=uuid.uuid4(), items=[
            PrescriptionItemCreate(medicine_name="Ibuprofen"),
        ])
        with pytest.raises(service.EncounterNotFound):
            await service.create_prescription(db, payload, created_by=doctor.id)

    async def test_duration_days_persists_as_integer(self, db, seed, encounter):
        """Regression test: PrescriptionItem.duration_days was declared
        as UUID(as_uuid=True) instead of Integer -- a copy-paste bug
        that would have silently corrupted every prescription with a
        duration set. Confirms the fix holds."""
        _dept, _room, doctor = seed
        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(medicine_name="Azithromycin", duration_days=3),
        ])
        prescription, _warnings = await service.create_prescription(db, payload, created_by=doctor.id)
        items = await service.get_prescription_items(db, prescription.id)
        assert items[0].duration_days == 3
        assert isinstance(items[0].duration_days, int)


class TestGetPrescription:
    async def test_get_returns_none_for_unknown_id(self, db):
        result = await service.get_prescription(db, uuid.uuid4())
        assert result is None

    async def test_get_returns_saved_prescription(self, db, seed, encounter):
        _dept, _room, doctor = seed
        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(medicine_name="Cetirizine"),
        ])
        created, _warnings = await service.create_prescription(db, payload, created_by=doctor.id)
        fetched = await service.get_prescription(db, created.id)
        assert fetched is not None
        assert fetched.id == created.id


class TestAllergyOverrideColumns:
    """Schema-level checks only -- CDS wiring (the code that actually
    raises AllergyConflict and populates these columns) lands in the
    follow-up PR. This just confirms migration 0032's columns and CHECK
    constraint are correctly mirrored on the ORM model."""

    async def test_override_columns_accept_null_by_default(self, db, seed, encounter):
        _dept, _room, doctor = seed
        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(medicine_name="Metformin"),
        ])
        prescription, _warnings = await service.create_prescription(db, payload, created_by=doctor.id)
        items = await service.get_prescription_items(db, prescription.id)
        assert items[0].allergy_override_reason is None
        assert items[0].allergy_override_by is None

    async def test_override_reason_without_override_by_violates_check(self, db, seed, encounter):
        _dept, _room, doctor = seed
        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(medicine_name="Metformin"),
        ])
        prescription, _warnings = await service.create_prescription(db, payload, created_by=doctor.id)
        items = await service.get_prescription_items(db, prescription.id)
        items[0].allergy_override_reason = "Clinician judged risk acceptable given severity"
        # allergy_override_by deliberately left NULL -- CHECK requires both or neither
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_override_reason_too_short_violates_check(self, db, seed, encounter):
        _dept, _room, doctor = seed
        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(medicine_name="Metformin"),
        ])
        prescription, _warnings = await service.create_prescription(db, payload, created_by=doctor.id)
        items = await service.get_prescription_items(db, prescription.id)
        items[0].allergy_override_reason = "too short"  # < 20 chars
        items[0].allergy_override_by = doctor.id
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_valid_override_pair_is_accepted(self, db, seed, encounter):
        _dept, _room, doctor = seed
        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(medicine_name="Metformin"),
        ])
        prescription, _warnings = await service.create_prescription(db, payload, created_by=doctor.id)
        items = await service.get_prescription_items(db, prescription.id)
        items[0].allergy_override_reason = "Clinician judged risk acceptable given severity"
        items[0].allergy_override_by = doctor.id
        await db.flush()  # must not raise

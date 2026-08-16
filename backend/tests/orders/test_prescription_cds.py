"""
CDS wiring tests for app.orders.service.create_prescription -- the
allergy check (via app.allergies.service.check_prescription_item) and
the rule-based interaction stub (app.allergies.interactions), both
wired into the prescription-save path.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.allergies.service import AllergyConflict
from app.audit.models import AuditLog
from app.orders import service
from app.orders.schemas import PrescriptionCreate, PrescriptionItemCreate
from tests.orders.conftest import seed_allergy, seed_inventory_item

pytestmark = pytest.mark.asyncio


async def _last_audit_log(db, resource_id):
    result = await db.execute(
        select(AuditLog).where(AuditLog.resource_id == resource_id).order_by(AuditLog.chain_seq.desc())
    )
    return result.scalars().first()


class TestAllergyBlocking:
    async def test_matching_allergy_without_override_raises(self, db, seed, encounter, patient):
        _dept, _room, doctor = seed
        item = await seed_inventory_item(db, name="Amoxicillin 500mg", ingredient_code="PENICILLIN")
        await seed_allergy(db, patient_id=patient.id, recorded_by=doctor.id, ingredient_code="PENICILLIN")

        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(medicine_item_id=item.id, medicine_name=item.name),
        ])
        with pytest.raises(AllergyConflict) as exc_info:
            await service.create_prescription(db, payload, created_by=doctor.id)
        assert exc_info.value.absolute is False

    async def test_matching_allergy_with_short_override_reason_still_raises(
        self, db, seed, encounter, patient,
    ):
        _dept, _room, doctor = seed
        item = await seed_inventory_item(db, name="Amoxicillin 500mg", ingredient_code="PENICILLIN")
        await seed_allergy(db, patient_id=patient.id, recorded_by=doctor.id, ingredient_code="PENICILLIN")

        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(
                medicine_item_id=item.id, medicine_name=item.name, override_reason="too short",
            ),
        ])
        with pytest.raises(AllergyConflict):
            await service.create_prescription(db, payload, created_by=doctor.id)

    async def test_matching_allergy_with_valid_override_saves_and_audits(
        self, db, seed, encounter, patient,
    ):
        _dept, _room, doctor = seed
        item = await seed_inventory_item(db, name="Amoxicillin 500mg", ingredient_code="PENICILLIN")
        allergy = await seed_allergy(
            db, patient_id=patient.id, recorded_by=doctor.id, ingredient_code="PENICILLIN",
        )

        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(
                medicine_item_id=item.id, medicine_name=item.name,
                override_reason="Prior reaction was mild; benefit outweighs risk here",
            ),
        ])
        prescription, warnings = await service.create_prescription(db, payload, created_by=doctor.id)

        items = await service.get_prescription_items(db, prescription.id)
        assert items[0].allergy_override_reason == "Prior reaction was mild; benefit outweighs risk here"
        assert items[0].allergy_override_by == doctor.id

        log = await _last_audit_log(db, items[0].id)
        assert log is not None
        assert log.action == "allergy_override"
        assert log.resource_type == "prescription_items"
        assert log.new_value["allergy_id"] == str(allergy.id)

    async def test_anaphylaxis_never_overridable(self, db, seed, encounter, patient):
        _dept, _room, doctor = seed
        item = await seed_inventory_item(db, name="Amoxicillin 500mg", ingredient_code="PENICILLIN")
        await seed_allergy(
            db, patient_id=patient.id, recorded_by=doctor.id, ingredient_code="PENICILLIN",
            severity="anaphylaxis",
        )
        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(
                medicine_item_id=item.id, medicine_name=item.name,
                override_reason="Patient and family insist despite the documented history",
            ),
        ])
        with pytest.raises(AllergyConflict) as exc_info:
            await service.create_prescription(db, payload, created_by=doctor.id)
        assert exc_info.value.absolute is True

    async def test_item_with_no_ingredient_code_is_never_checked(self, db, seed, encounter, patient):
        """A free-text drug (no medicine_item_id, or an inventory item
        with no ingredient_code set) can never be matched -- must save
        cleanly regardless of the patient's allergy list."""
        _dept, _room, doctor = seed
        await seed_allergy(db, patient_id=patient.id, recorded_by=doctor.id, ingredient_code="PENICILLIN")

        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(medicine_name="Herbal cough syrup (not in catalog)"),
        ])
        prescription, warnings = await service.create_prescription(db, payload, created_by=doctor.id)
        items = await service.get_prescription_items(db, prescription.id)
        assert items[0].allergy_override_reason is None
        assert len(warnings) == 1
        assert "Herbal cough syrup" in warnings[0]
        assert "not performed" in warnings[0]


class TestInteractionWarnings:
    async def test_conflicting_pair_surfaces_warning_without_blocking(self, db, seed, encounter):
        _dept, _room, doctor = seed
        warfarin = await seed_inventory_item(db, name="Warfarin 5mg", ingredient_code="WARFARIN")
        aspirin = await seed_inventory_item(db, name="Aspirin 75mg", ingredient_code="ASPIRIN")

        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(medicine_item_id=warfarin.id, medicine_name=warfarin.name),
            PrescriptionItemCreate(medicine_item_id=aspirin.id, medicine_name=aspirin.name),
        ])
        prescription, warnings = await service.create_prescription(db, payload, created_by=doctor.id)

        assert prescription.id is not None  # the save was not blocked
        assert len(warnings) == 1
        assert "Warfarin" in warnings[0] and "Aspirin" in warnings[0]

    async def test_non_conflicting_items_produce_no_warnings(self, db, seed, encounter):
        _dept, _room, doctor = seed
        paracetamol = await seed_inventory_item(db, name="Paracetamol 500mg", ingredient_code="PARACETAMOL")
        cetirizine = await seed_inventory_item(db, name="Cetirizine 10mg", ingredient_code="CETIRIZINE")

        payload = PrescriptionCreate(encounter_id=encounter.id, items=[
            PrescriptionItemCreate(medicine_item_id=paracetamol.id, medicine_name=paracetamol.name),
            PrescriptionItemCreate(medicine_item_id=cetirizine.id, medicine_name=cetirizine.name),
        ])
        _prescription, warnings = await service.create_prescription(db, payload, created_by=doctor.id)
        assert warnings == []

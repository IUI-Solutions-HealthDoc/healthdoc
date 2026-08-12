from __future__ import annotations

import uuid

import pytest

from app.allergies.models import Allergy
from app.allergies.service import AllergyConflict, check_prescription_item
from app.common.enums import AllergenType, AllergySeverity, AllergyStatus
from app.inventory.models import DrugInteraction
from app.pharmacy.interactions import DrugInteractionConflict, check_against_existing


@pytest.mark.asyncio
async def test_allergy_check_unit_moderate_severity(db):
    patient_id = uuid.uuid4()
    doctor_id = uuid.uuid4()

    allergy = Allergy(
        id=uuid.uuid4(),
        patient_id=patient_id,
        allergen_type=AllergenType.DRUG.value,
        substance_text="Amoxicillin",
        ingredient_code="ING_AMOX",
        severity=AllergySeverity.MODERATE.value,
        status=AllergyStatus.ACTIVE.value,
        recorded_by=doctor_id,
        created_by=doctor_id,
    )
    db.add(allergy)
    await db.flush()

    # 1. No override -> raises AllergyConflict
    with pytest.raises(AllergyConflict) as exc_info:
        await check_prescription_item(db, patient_id=patient_id, ingredient_code="ING_AMOX")
    assert exc_info.value.absolute is False

    # 2. Short override (< 20 chars) -> raises AllergyConflict
    with pytest.raises(AllergyConflict):
        await check_prescription_item(
            db, patient_id=patient_id, ingredient_code="ING_AMOX", override_reason="Short reason"
        )

    # 3. Valid override (>= 20 chars) -> returns matched Allergy
    match = await check_prescription_item(
        db,
        patient_id=patient_id,
        ingredient_code="ING_AMOX",
        override_reason="Patient previously tolerated amoxicillin without any adverse events",
    )
    assert match is not None
    assert match.ingredient_code == "ING_AMOX"


@pytest.mark.asyncio
async def test_allergy_check_unit_anaphylaxis_severity(db):
    patient_id = uuid.uuid4()
    doctor_id = uuid.uuid4()

    allergy = Allergy(
        id=uuid.uuid4(),
        patient_id=patient_id,
        allergen_type=AllergenType.DRUG.value,
        substance_text="Penicillin Anaphylaxis",
        ingredient_code="ING_PENI",
        severity=AllergySeverity.ANAPHYLAXIS.value,
        status=AllergyStatus.ACTIVE.value,
        recorded_by=doctor_id,
        created_by=doctor_id,
    )
    db.add(allergy)
    await db.flush()

    # Even with long override reason, anaphylaxis cannot be overridden
    with pytest.raises(AllergyConflict) as exc_info:
        await check_prescription_item(
            db,
            patient_id=patient_id,
            ingredient_code="ING_PENI",
            override_reason="Attempting to override anaphylaxis allergy with supervision",
        )
    assert exc_info.value.absolute is True


@pytest.mark.asyncio
async def test_drug_interaction_check_unit(db):
    lo, hi = sorted(("ING_ALPHA", "ING_BETA"))
    interaction = DrugInteraction(
        id=uuid.uuid4(),
        ingredient_code_a=lo,
        ingredient_code_b=hi,
        severity="major",
        description="Interaction between Alpha and Beta",
        is_active=True,
    )
    db.add(interaction)
    await db.flush()

    # 1. Without override -> raises DrugInteractionConflict
    with pytest.raises(DrugInteractionConflict) as exc_info:
        await check_against_existing(
            db,
            new_ingredient_code="ING_BETA",
            existing_ingredient_codes=["ING_ALPHA"],
        )
    assert exc_info.value.absolute is False

    # 2. Short override -> raises DrugInteractionConflict
    with pytest.raises(DrugInteractionConflict):
        await check_against_existing(
            db,
            new_ingredient_code="ING_BETA",
            existing_ingredient_codes=["ING_ALPHA"],
            override_reason="Too short",
        )

    # 3. Valid override -> returns interaction
    res = await check_against_existing(
        db,
        new_ingredient_code="ING_BETA",
        existing_ingredient_codes=["ING_ALPHA"],
        override_reason="Benefit outweighs risk; patient monitored closely by doctor",
    )
    assert res is not None


@pytest.mark.asyncio
async def test_drug_interaction_contraindicated_absolute(db):
    lo, hi = sorted(("ING_WARFARIN", "ING_ASPIRIN"))
    interaction = DrugInteraction(
        id=uuid.uuid4(),
        ingredient_code_a=lo,
        ingredient_code_b=hi,
        severity="contraindicated",
        description="Contraindicated combination",
        is_active=True,
    )
    db.add(interaction)
    await db.flush()

    with pytest.raises(DrugInteractionConflict) as exc_info:
        await check_against_existing(
            db,
            new_ingredient_code="ING_ASPIRIN",
            existing_ingredient_codes=["ING_WARFARIN"],
            override_reason="Attempting override on contraindicated pair with monitoring",
        )
    assert exc_info.value.absolute is True

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.common.enums import DispenseStatus
from app.pharmacy.schemas import DispenseCreate, DispenseItemCreate
from app.pharmacy.service import create_dispense, get_expiry_tracker


@pytest.mark.asyncio
async def test_pre_dispense_allergy_check_blocks_and_overrides(db_session, pharmacy_seed):
    facility_id = pharmacy_seed["facility_id"]
    patient_id = pharmacy_seed["patient_id"]
    pharmacist_id = pharmacy_seed["pharmacist_id"]
    prescription_id = pharmacy_seed["prescription_id"]
    prescription_item_id = pharmacy_seed["prescription_item_id"]
    medicine_id = pharmacy_seed["medicine_id"]

    ingredient_code = "ING_PARA_TEST"
    await db_session.execute(
        text("UPDATE inventory_items SET ingredient_code = :code WHERE id = :id"),
        {"code": ingredient_code, "id": medicine_id},
    )

    allergy_id = uuid.uuid4()
    await db_session.execute(
        text("""
            INSERT INTO allergies
                (id, patient_id, allergen_type, substance_text, ingredient_code, severity, status, recorded_by, created_by)
            VALUES
                (:id, :patient_id, 'drug', 'Paracetamol Allergy', :code, 'moderate', 'active', :user, :user)
        """),
        {
            "id": allergy_id,
            "patient_id": patient_id,
            "code": ingredient_code,
            "user": pharmacist_id,
        },
    )
    await db_session.flush()

    # 1. Attempt dispense without override reason -> 422 allergy_conflict
    with pytest.raises(HTTPException) as exc_info:
        await create_dispense(
            db_session,
            DispenseCreate(
                prescription_id=prescription_id,
                items=[DispenseItemCreate(
                    prescription_item_id=prescription_item_id,
                    quantity_dispensed=Decimal("2"),
                )],
            ),
            current_user_id=pharmacist_id,
            facility_id=facility_id,
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "allergy_conflict"

    # 2. Attempt dispense with short override reason (< 20 chars) -> 422 allergy_conflict
    with pytest.raises(HTTPException) as exc_info:
        await create_dispense(
            db_session,
            DispenseCreate(
                prescription_id=prescription_id,
                items=[DispenseItemCreate(
                    prescription_item_id=prescription_item_id,
                    quantity_dispensed=Decimal("2"),
                    allergy_override_reason="too short",
                )],
            ),
            current_user_id=pharmacist_id,
            facility_id=facility_id,
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "allergy_conflict"

    # 3. Dispense with valid override reason (>= 20 chars) -> succeeds
    valid_reason = "Patient tolerated paracetamol previously under monitoring without issues"
    dispense = await create_dispense(
        db_session,
        DispenseCreate(
            prescription_id=prescription_id,
            items=[DispenseItemCreate(
                prescription_item_id=prescription_item_id,
                quantity_dispensed=Decimal("2"),
                allergy_override_reason=valid_reason,
            )],
        ),
        current_user_id=pharmacist_id,
        facility_id=facility_id,
    )
    assert dispense.status == DispenseStatus.DISPENSED


@pytest.mark.asyncio
async def test_pre_dispense_anaphylaxis_allergy_cannot_be_overridden(db_session, pharmacy_seed):
    facility_id = pharmacy_seed["facility_id"]
    patient_id = pharmacy_seed["patient_id"]
    pharmacist_id = pharmacy_seed["pharmacist_id"]
    prescription_id = pharmacy_seed["prescription_id"]
    prescription_item_id = pharmacy_seed["prescription_item_id"]
    medicine_id = pharmacy_seed["medicine_id"]

    ingredient_code = "ING_ANAPH_TEST"
    await db_session.execute(
        text("UPDATE inventory_items SET ingredient_code = :code WHERE id = :id"),
        {"code": ingredient_code, "id": medicine_id},
    )

    allergy_id = uuid.uuid4()
    await db_session.execute(
        text("""
            INSERT INTO allergies
                (id, patient_id, allergen_type, substance_text, ingredient_code, severity, status, recorded_by, created_by)
            VALUES
                (:id, :patient_id, 'drug', 'Severe Paracetamol Reaction', :code, 'anaphylaxis', 'active', :user, :user)
        """),
        {
            "id": allergy_id,
            "patient_id": patient_id,
            "code": ingredient_code,
            "user": pharmacist_id,
        },
    )
    await db_session.flush()

    # Even with long override reason, anaphylaxis cannot be overridden
    with pytest.raises(HTTPException) as exc_info:
        await create_dispense(
            db_session,
            DispenseCreate(
                prescription_id=prescription_id,
                items=[DispenseItemCreate(
                    prescription_item_id=prescription_item_id,
                    quantity_dispensed=Decimal("2"),
                    allergy_override_reason="Attempting override for anaphylaxis patient with caution",
                )],
            ),
            current_user_id=pharmacist_id,
            facility_id=facility_id,
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "allergy_conflict"
    assert exc_info.value.detail["absolute"] is True


@pytest.mark.asyncio
async def test_pre_dispense_drug_interaction_check(db_session, pharmacy_seed):
    facility_id = pharmacy_seed["facility_id"]
    pharmacist_id = pharmacy_seed["pharmacist_id"]
    prescription_id = pharmacy_seed["prescription_id"]
    prescription_item_id_a = pharmacy_seed["prescription_item_id"]

    # Create second medicine item and prescription item
    medicine_id_b = uuid.uuid4()
    prescription_item_id_b = uuid.uuid4()
    code_a = "DRUG_ALPHA"
    code_b = "DRUG_BETA"

    await db_session.execute(
        text("UPDATE inventory_items SET ingredient_code = :code WHERE id = :id"),
        {"code": code_a, "id": pharmacy_seed["medicine_id"]},
    )
    await db_session.execute(
        text("""
            INSERT INTO inventory_items (id, name, generic_name, strength, form, item_type, ingredient_code)
            VALUES (:id, 'Test Beta', 'Beta Drug', '100mg', 'tablet', 'medicine', :code)
        """),
        {"id": medicine_id_b, "code": code_b},
    )
    await db_session.execute(
        text("""
            INSERT INTO prescription_items (id, prescription_id, medicine_item_id, medicine_name)
            VALUES (:id, :prescription_id, :medicine_id, 'Test Beta')
        """),
        {"id": prescription_item_id_b, "prescription_id": prescription_id, "medicine_id": medicine_id_b},
    )

    # Insert batch for medicine B
    location_id = (await db_session.execute(
        text("SELECT id FROM stock_locations WHERE facility_id = :fac LIMIT 1"),
        {"fac": facility_id},
    )).scalar_one()
    await db_session.execute(
        text("""
            INSERT INTO inventory_batches (id, item_id, batch_number, expiry_date, quantity, stock_location_id)
            VALUES (:id, :item, 'BATCH_B', :expiry, 50, :loc)
        """),
        {
            "id": uuid.uuid4(),
            "item": medicine_id_b,
            "expiry": date.today() + timedelta(days=60),
            "loc": location_id,
        },
    )

    # Seed drug interaction in drug_interactions table (ordered ingredient_code_a < ingredient_code_b)
    interaction_id = uuid.uuid4()
    lo_code, hi_code = sorted((code_a, code_b))
    await db_session.execute(
        text("""
            INSERT INTO drug_interactions (id, ingredient_code_a, ingredient_code_b, severity, description, is_active)
            VALUES (:id, :a, :b, 'major', 'Severe interaction between Alpha and Beta', true)
        """),
        {"id": interaction_id, "a": lo_code, "b": hi_code},
    )
    await db_session.flush()

    # 1. Dispense both items without interaction override -> 422 drug_interaction_conflict
    with pytest.raises(HTTPException) as exc_info:
        await create_dispense(
            db_session,
            DispenseCreate(
                prescription_id=prescription_id,
                items=[
                    DispenseItemCreate(prescription_item_id=prescription_item_id_a, quantity_dispensed=Decimal("2")),
                    DispenseItemCreate(prescription_item_id=prescription_item_id_b, quantity_dispensed=Decimal("2")),
                ],
            ),
            current_user_id=pharmacist_id,
            facility_id=facility_id,
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "drug_interaction_conflict"

    # 2. Dispense with valid interaction override reason -> succeeds
    override_reason = "Benefit outweighs risk; monitored co-administration approved by physician"
    dispense = await create_dispense(
        db_session,
        DispenseCreate(
            prescription_id=prescription_id,
            items=[
                DispenseItemCreate(prescription_item_id=prescription_item_id_a, quantity_dispensed=Decimal("2")),
                DispenseItemCreate(
                    prescription_item_id=prescription_item_id_b,
                    quantity_dispensed=Decimal("2"),
                    interaction_override_reason=override_reason,
                ),
            ],
        ),
        current_user_id=pharmacist_id,
        facility_id=facility_id,
    )
    assert dispense.status == DispenseStatus.DISPENSED


@pytest.mark.asyncio
async def test_expiry_tracker_returns_expiring_batches(db_session, pharmacy_seed):
    facility_id = pharmacy_seed["facility_id"]
    result = await get_expiry_tracker(
        db_session,
        facility_id=facility_id,
        stock_location_id=None,
        threshold_days=30,
    )
    assert result.threshold_days == 30
    assert len(result.items) >= 1
    assert any(b.batch_number == "EARLY" for b in result.items)


@pytest.mark.asyncio
async def test_low_stock_notification_and_audit_log(db_session, pharmacy_seed):
    facility_id = pharmacy_seed["facility_id"]
    pharmacist_id = pharmacy_seed["pharmacist_id"]
    medicine_id = pharmacy_seed["medicine_id"]
    prescription_id = pharmacy_seed["prescription_id"]
    prescription_item_id = pharmacy_seed["prescription_item_id"]

    # Set reorder_level on inventory item to 20. Current total quantity is 6 + 20 = 26.
    await db_session.execute(
        text("UPDATE inventory_items SET reorder_level = 20 WHERE id = :id"),
        {"id": medicine_id},
    )
    await db_session.flush()

    # Dispense 10 units. Total remaining drops to 16, which is <= reorder_level 20.
    result = await create_dispense(
        db_session,
        DispenseCreate(
            prescription_id=prescription_id,
            items=[DispenseItemCreate(
                prescription_item_id=prescription_item_id,
                quantity_dispensed=Decimal("10"),
            )],
        ),
        current_user_id=pharmacist_id,
        facility_id=facility_id,
    )
    assert result.status == DispenseStatus.DISPENSED

    debug_row = (await db_session.execute(text(
        "SELECT COALESCE(SUM(quantity),0) AS total, reorder_level FROM inventory_batches ib "
        "JOIN inventory_items ii ON ii.id = ib.item_id "
        "WHERE ib.item_id = :item_id GROUP BY reorder_level"
    ), {"item_id": medicine_id})).mappings().first()
    

    # Verify notification_history row inserted
    notif_count = (await db_session.execute(text(
        "SELECT count(*) FROM notification_history WHERE event_type IN ('low_stock', 'out_of_stock')"
    ))).scalar_one()
    assert notif_count >= 1

    # Verify audit_log inserted for dispense creation
    audit_count = (await db_session.execute(text(
        "SELECT count(*) FROM audit_logs WHERE resource_id = :id AND action = 'create'"
    ), {"id": result.id})).scalar_one()
    assert audit_count == 1



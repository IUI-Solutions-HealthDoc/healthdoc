import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.common.enums import DispenseStatus
from app.pharmacy.schemas import DispenseCreate, DispenseItemCreate
from app.pharmacy.service import create_dispense


def _seed_prescription(fake_session, prescription_id, patient_id):
    fake_session.db["prescriptions"][str(prescription_id)] = {
        "id": prescription_id, "patient_id": patient_id, "encounter_id": uuid.uuid4(),
    }


def _seed_prescription_item(fake_session, prescription_item_id, medicine_item_id):
    fake_session.db["prescription_items"][str(prescription_item_id)] = {
        "medicine_item_id": medicine_item_id,
    }


def _seed_batch(fake_session, batch_id, item_id, quantity, *, batch_number="B1", expiry=date(2027, 1, 1)):
    fake_session.db["inventory_batches"][str(batch_id)] = {
        "id": batch_id, "item_id": item_id, "quantity": Decimal(quantity),
        "batch_number": batch_number, "expiry_date": expiry,
    }

async def test_manual_batch_pin_still_works_unchanged(fake_session, audit_log):
    prescription_id, patient_id = uuid.uuid4(), uuid.uuid4()
    batch_id, item_id = uuid.uuid4(), uuid.uuid4()

    _seed_prescription(fake_session, prescription_id, patient_id)
    _seed_batch(fake_session, batch_id, item_id, "50")

    payload = DispenseCreate(
        prescription_id=prescription_id,
        items=[DispenseItemCreate(
            prescription_item_id=uuid.uuid4(), batch_id=batch_id,
            quantity_dispensed=Decimal("10"),
        )],
    )

    result = await create_dispense(
        fake_session, payload, current_user_id=uuid.uuid4(), facility_id=uuid.uuid4()
    )

    assert result.status == DispenseStatus.DISPENSED
    assert result.items[0].quantity_dispensed == Decimal("10")
    assert len(result.items[0].item_row_ids) == 1
    assert fake_session.db["inventory_batches"][str(batch_id)]["quantity"] == Decimal("40")
    assert len(audit_log.calls) == 1


async def test_manual_batch_pin_insufficient_stock_rejects_whole_request(fake_session, audit_log):
    prescription_id, patient_id = uuid.uuid4(), uuid.uuid4()
    batch_id, item_id = uuid.uuid4(), uuid.uuid4()

    _seed_prescription(fake_session, prescription_id, patient_id)
    _seed_batch(fake_session, batch_id, item_id, "3")

    payload = DispenseCreate(
        prescription_id=prescription_id,
        items=[DispenseItemCreate(
            prescription_item_id=uuid.uuid4(), batch_id=batch_id,
            quantity_dispensed=Decimal("10"),
        )],
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_dispense(
            fake_session, payload, current_user_id=uuid.uuid4(), facility_id=uuid.uuid4()
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "insufficient_stock"
    assert fake_session.db["inventory_batches"][str(batch_id)]["quantity"] == Decimal("3")
    assert audit_log.calls == []



async def test_fefo_auto_selects_earliest_expiry_single_batch(fake_session, audit_log):
    prescription_id, patient_id = uuid.uuid4(), uuid.uuid4()
    prescription_item_id, medicine_item_id = uuid.uuid4(), uuid.uuid4()
    facility_id = uuid.uuid4()
    early_batch, late_batch = uuid.uuid4(), uuid.uuid4()

    _seed_prescription(fake_session, prescription_id, patient_id)
    _seed_prescription_item(fake_session, prescription_item_id, medicine_item_id)
    _seed_batch(fake_session, early_batch, medicine_item_id, "20",
                batch_number="EARLY", expiry=date(2026, 8, 1))
    _seed_batch(fake_session, late_batch, medicine_item_id, "20",
                batch_number="LATE", expiry=date(2027, 6, 1))

    payload = DispenseCreate(
        prescription_id=prescription_id,
        items=[DispenseItemCreate(
            prescription_item_id=prescription_item_id, quantity_dispensed=Decimal("5"),
        )],
    )

    result = await create_dispense(
        fake_session, payload, current_user_id=uuid.uuid4(), facility_id=facility_id
    )

    assert result.status == DispenseStatus.DISPENSED
    item = result.items[0]
    assert len(item.batches) == 1
    assert item.batches[0].batch_number == "EARLY"
    assert fake_session.db["inventory_batches"][str(early_batch)]["quantity"] == Decimal("15")
    assert fake_session.db["inventory_batches"][str(late_batch)]["quantity"] == Decimal("20")


async def test_fefo_splits_across_batches_when_one_is_insufficient(fake_session, audit_log):
    prescription_id, patient_id = uuid.uuid4(), uuid.uuid4()
    prescription_item_id, medicine_item_id = uuid.uuid4(), uuid.uuid4()
    facility_id = uuid.uuid4()
    early_batch, late_batch = uuid.uuid4(), uuid.uuid4()

    _seed_prescription(fake_session, prescription_id, patient_id)
    _seed_prescription_item(fake_session, prescription_item_id, medicine_item_id)
    _seed_batch(fake_session, early_batch, medicine_item_id, "6",
                batch_number="EARLY", expiry=date(2026, 8, 1))
    _seed_batch(fake_session, late_batch, medicine_item_id, "20",
                batch_number="LATE", expiry=date(2027, 6, 1))

    payload = DispenseCreate(
        prescription_id=prescription_id,
        items=[DispenseItemCreate(
            prescription_item_id=prescription_item_id, quantity_dispensed=Decimal("10"),
        )],
    )

    result = await create_dispense(
        fake_session, payload, current_user_id=uuid.uuid4(), facility_id=facility_id
    )

    item = result.items[0]
    assert item.quantity_dispensed == Decimal("10")
    assert not item.is_partial
    assert len(item.batches) == 2
    assert item.batches[0].batch_number == "EARLY"
    assert item.batches[0].quantity_from_batch == Decimal("6")
    assert item.batches[1].batch_number == "LATE"
    assert item.batches[1].quantity_from_batch == Decimal("4")
    assert fake_session.db["inventory_batches"][str(early_batch)]["quantity"] == Decimal("0")
    assert fake_session.db["inventory_batches"][str(late_batch)]["quantity"] == Decimal("16")
    assert len(fake_session.db["stock_ledger"]) == 2


async def test_allow_partial_dispenses_available_stock_and_marks_partial(fake_session, audit_log):
    prescription_id, patient_id = uuid.uuid4(), uuid.uuid4()
    prescription_item_id, medicine_item_id = uuid.uuid4(), uuid.uuid4()
    facility_id = uuid.uuid4()
    batch_id = uuid.uuid4()

    _seed_prescription(fake_session, prescription_id, patient_id)
    _seed_prescription_item(fake_session, prescription_item_id, medicine_item_id)
    _seed_batch(fake_session, batch_id, medicine_item_id, "4")

    payload = DispenseCreate(
        prescription_id=prescription_id,
        allow_partial=True,
        items=[DispenseItemCreate(
            prescription_item_id=prescription_item_id, quantity_dispensed=Decimal("10"),
        )],
    )

    result = await create_dispense(
        fake_session, payload, current_user_id=uuid.uuid4(), facility_id=facility_id
    )

    assert result.status == DispenseStatus.PARTIALLY_DISPENSED
    item = result.items[0]
    assert item.quantity_dispensed == Decimal("4")
    assert item.quantity_prescribed == Decimal("10")
    assert item.is_partial is True
    assert fake_session.db["inventory_batches"][str(batch_id)]["quantity"] == Decimal("0")
    assert len(audit_log.calls) == 1


async def test_allow_partial_with_zero_stock_marks_out_of_stock(fake_session, audit_log):
    prescription_id, patient_id = uuid.uuid4(), uuid.uuid4()
    prescription_item_id, medicine_item_id = uuid.uuid4(), uuid.uuid4()
    facility_id = uuid.uuid4()

    _seed_prescription(fake_session, prescription_id, patient_id)
    _seed_prescription_item(fake_session, prescription_item_id, medicine_item_id)

    payload = DispenseCreate(
        prescription_id=prescription_id,
        allow_partial=True,
        items=[DispenseItemCreate(
            prescription_item_id=prescription_item_id, quantity_dispensed=Decimal("10"),
        )],
    )

    result = await create_dispense(
        fake_session, payload, current_user_id=uuid.uuid4(), facility_id=facility_id
    )

    assert result.status == DispenseStatus.OUT_OF_STOCK
    assert result.items[0].quantity_dispensed == Decimal("0")
    assert result.items[0].batches == []


async def test_without_allow_partial_insufficient_fefo_stock_rejects_and_mutates_nothing(
    fake_session, audit_log
):
    prescription_id, patient_id = uuid.uuid4(), uuid.uuid4()
    prescription_item_id, medicine_item_id = uuid.uuid4(), uuid.uuid4()
    facility_id = uuid.uuid4()
    batch_id = uuid.uuid4()

    _seed_prescription(fake_session, prescription_id, patient_id)
    _seed_prescription_item(fake_session, prescription_item_id, medicine_item_id)
    _seed_batch(fake_session, batch_id, medicine_item_id, "2")

    payload = DispenseCreate(
        prescription_id=prescription_id,
        allow_partial=False,
        items=[DispenseItemCreate(
            prescription_item_id=prescription_item_id, quantity_dispensed=Decimal("10"),
        )],
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_dispense(
            fake_session, payload, current_user_id=uuid.uuid4(), facility_id=facility_id
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "insufficient_stock"
    assert exc_info.value.detail["short_by"] == "8"
    assert fake_session.db["inventory_batches"][str(batch_id)]["quantity"] == Decimal("2")
    assert fake_session.db["pharmacy_dispenses"] == []
    assert audit_log.calls == []



async def test_substitution_creates_pending_row_without_touching_stock(fake_session, audit_log):
    prescription_id, patient_id = uuid.uuid4(), uuid.uuid4()
    doctor_id = uuid.uuid4()
    substitute_item_id = uuid.uuid4()
    prescription_item_id = uuid.uuid4()

    _seed_prescription(fake_session, prescription_id, patient_id)
    fake_session.db["prescription_doctor_patient"][str(prescription_id)] = {
        "doctor_id": doctor_id, "patient_id": patient_id,
    }

    payload = DispenseCreate(
        prescription_id=prescription_id,
        items=[DispenseItemCreate(
            prescription_item_id=prescription_item_id,
            quantity_dispensed=Decimal("5"),
            substitute_item_id=substitute_item_id,
            substitute_reason="Out of stock, generic equivalent available",
        )],
    )

    result = await create_dispense(
        fake_session, payload, current_user_id=uuid.uuid4(), facility_id=uuid.uuid4()
    )

    assert result.status == DispenseStatus.DOCTOR_APPROVAL_REQUIRED
    item = result.items[0]
    assert item.approval_status == "pending"
    assert item.is_substitute is True
    assert item.substitute_item_id == substitute_item_id
    assert item.quantity_dispensed == Decimal("0")
    assert item.batches == []

    assert fake_session.db["stock_ledger"] == []

    assert len(fake_session.db["notifications"]) == 1
    assert fake_session.db["notifications"][0]["recipient_user_id"] == str(doctor_id)

    assert len(audit_log.calls) == 1


async def test_substitution_mixed_with_normal_item_status_reflects_pending(fake_session, audit_log):
    """One normal item fully fills, one item is a pending substitution —
    overall status must be DOCTOR_APPROVAL_REQUIRED (the more-blocking
    state), not DISPENSED just because the other item succeeded."""
    prescription_id, patient_id = uuid.uuid4(), uuid.uuid4()
    batch_id, item_id = uuid.uuid4(), uuid.uuid4()

    _seed_prescription(fake_session, prescription_id, patient_id)
    _seed_batch(fake_session, batch_id, item_id, "50")

    payload = DispenseCreate(
        prescription_id=prescription_id,
        items=[
            DispenseItemCreate(
                prescription_item_id=uuid.uuid4(), batch_id=batch_id,
                quantity_dispensed=Decimal("5"),
            ),
            DispenseItemCreate(
                prescription_item_id=uuid.uuid4(), quantity_dispensed=Decimal("3"),
                substitute_item_id=uuid.uuid4(), substitute_reason="allergy",
            ),
        ],
    )

    result = await create_dispense(
        fake_session, payload, current_user_id=uuid.uuid4(), facility_id=uuid.uuid4()
    )

    assert result.status == DispenseStatus.DOCTOR_APPROVAL_REQUIRED
    assert len(result.items) == 2




async def test_second_dispense_supersedes_first_as_new_version(fake_session, audit_log):
    prescription_id, patient_id = uuid.uuid4(), uuid.uuid4()
    prescription_item_id, medicine_item_id = uuid.uuid4(), uuid.uuid4()
    facility_id = uuid.uuid4()
    batch_id = uuid.uuid4()

    _seed_prescription(fake_session, prescription_id, patient_id)
    _seed_prescription_item(fake_session, prescription_item_id, medicine_item_id)
    _seed_batch(fake_session, batch_id, medicine_item_id, "100")

    payload = DispenseCreate(
        prescription_id=prescription_id,
        items=[DispenseItemCreate(
            prescription_item_id=prescription_item_id, quantity_dispensed=Decimal("5"),
        )],
    )

    first = await create_dispense(
        fake_session, payload, current_user_id=uuid.uuid4(), facility_id=facility_id
    )
    second = await create_dispense(
        fake_session, payload, current_user_id=uuid.uuid4(), facility_id=facility_id
    )

    assert first.version == 1
    assert second.version == 2
    current_rows = [d for d in fake_session.db["pharmacy_dispenses"] if d["is_current"]]
    assert len(current_rows) == 1
    assert current_rows[0]["id"] == str(second.id)
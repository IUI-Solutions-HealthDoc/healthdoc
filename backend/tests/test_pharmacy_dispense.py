import uuid
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


def _seed_batch(fake_session, batch_id, item_id, quantity):
    fake_session.db["inventory_batches"][str(batch_id)] = {
        "id": batch_id, "item_id": item_id, "quantity": Decimal(quantity),
    }


async def test_create_dispense_success_deducts_stock_and_writes_audit(fake_session, audit_log):
    prescription_id, patient_id = uuid.uuid4(), uuid.uuid4()
    batch_id, item_id = uuid.uuid4(), uuid.uuid4()
    prescription_item_id = uuid.uuid4()
    user_id, facility_id = uuid.uuid4(), uuid.uuid4()

    _seed_prescription(fake_session, prescription_id, patient_id)
    _seed_batch(fake_session, batch_id, item_id, "50")

    payload = DispenseCreate(
        prescription_id=prescription_id,
        items=[DispenseItemCreate(
            prescription_item_id=prescription_item_id, batch_id=batch_id,
            quantity_dispensed=Decimal("10"),
        )],
    )

    result = await create_dispense(
        fake_session, payload, current_user_id=user_id, facility_id=facility_id
    )

    assert result.status == DispenseStatus.DISPENSED
    assert result.version == 1
    assert result.is_current is True
    assert len(result.items) == 1
    assert result.items[0].quantity_dispensed == Decimal("10")

    assert fake_session.db["inventory_batches"][str(batch_id)]["quantity"] == Decimal("40")
    assert len(fake_session.db["stock_ledger"]) == 1
    assert fake_session.db["stock_ledger"][0]["quantity"] == Decimal("-10")

    assert len(audit_log.calls) == 1
    call = audit_log.calls[0]
    assert call["action"] == "create"
    assert call["resource_type"] == "pharmacy_dispenses"
    assert call["patient_id"] == patient_id
    assert call["facility_id"] == facility_id
    assert call["user_id"] == user_id


async def test_create_dispense_insufficient_stock_is_atomic(fake_session, audit_log):
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
    assert fake_session.db["pharmacy_dispenses"] == []
    assert fake_session.db["stock_ledger"] == []
    assert audit_log.calls == []


async def test_create_dispense_prescription_not_found_raises_404(fake_session, audit_log):
    payload = DispenseCreate(
        prescription_id=uuid.uuid4(),
        items=[DispenseItemCreate(
            prescription_item_id=uuid.uuid4(), batch_id=uuid.uuid4(),
            quantity_dispensed=Decimal("1"),
        )],
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_dispense(
            fake_session, payload, current_user_id=uuid.uuid4(), facility_id=uuid.uuid4()
        )

    assert exc_info.value.status_code == 404
    assert audit_log.calls == []


async def test_create_dispense_second_version_supersedes_first(fake_session, audit_log):
    prescription_id, patient_id = uuid.uuid4(), uuid.uuid4()
    batch_id, item_id = uuid.uuid4(), uuid.uuid4()

    _seed_prescription(fake_session, prescription_id, patient_id)
    _seed_batch(fake_session, batch_id, item_id, "100")

    payload = DispenseCreate(
        prescription_id=prescription_id,
        items=[DispenseItemCreate(
            prescription_item_id=uuid.uuid4(), batch_id=batch_id,
            quantity_dispensed=Decimal("5"),
        )],
    )

    first = await create_dispense(
        fake_session, payload, current_user_id=uuid.uuid4(), facility_id=uuid.uuid4()
    )
    second = await create_dispense(
        fake_session, payload, current_user_id=uuid.uuid4(), facility_id=uuid.uuid4()
    )

    assert first.version == 1
    assert second.version == 2
    assert second.is_current is True

    dispenses = fake_session.db["pharmacy_dispenses"]
    current_rows = [d for d in dispenses if d["is_current"]]
    assert len(current_rows) == 1
    assert current_rows[0]["id"] == str(second.id)

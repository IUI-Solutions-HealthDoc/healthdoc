import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.common.enums import DispenseStatus
from app.pharmacy.schemas import SubstitutionApprovalRequest
from app.pharmacy.service import approve_substitution


def _seed_pending_item(fake_session, *, item_row_id, dispense_id, prescription_id,
                        prescription_item_id, substitute_item_id, quantity_prescribed):
    fake_session.db["pharmacy_dispenses"].append({
        "id": dispense_id, "prescription_id": prescription_id,
        "status": DispenseStatus.DOCTOR_APPROVAL_REQUIRED, "is_current": True,
    })
    fake_session.db["pharmacy_dispense_items"].append({
        "id": item_row_id, "dispense_id": dispense_id,
        "prescription_item_id": prescription_item_id,
        "quantity_prescribed": Decimal(quantity_prescribed),
        "quantity_dispensed": None,
        "substitute_item_id": substitute_item_id,
        "approval_status": "pending",
    })


def _seed_batch(fake_session, batch_id, item_id, quantity, *, batch_number="B1", expiry=date(2027, 1, 1)):
    fake_session.db["inventory_batches"][str(batch_id)] = {
        "id": batch_id, "item_id": item_id, "quantity": Decimal(quantity),
        "batch_number": batch_number, "expiry_date": expiry,
    }


async def test_approve_debits_stock_and_marks_approved(fake_session, audit_log):
    item_row_id, dispense_id = str(uuid.uuid4()), str(uuid.uuid4())
    prescription_id = uuid.uuid4()
    substitute_item_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    doctor_id, facility_id = uuid.uuid4(), uuid.uuid4()

    _seed_pending_item(
        fake_session, item_row_id=item_row_id, dispense_id=dispense_id,
        prescription_id=prescription_id, prescription_item_id=uuid.uuid4(),
        substitute_item_id=substitute_item_id, quantity_prescribed="5",
    )
    _seed_batch(fake_session, batch_id, substitute_item_id, "20")

    result = await approve_substitution(
        fake_session, SubstitutionApprovalRequest(approved=True),
        item_row_id=item_row_id, approving_user_id=doctor_id, facility_id=facility_id,
    )

    assert result.approval_status == "approved"
    assert result.quantity_dispensed == Decimal("5")
    assert len(result.batches) == 1
    assert fake_session.db["inventory_batches"][str(batch_id)]["quantity"] == Decimal("15")
    assert len(fake_session.db["stock_ledger"]) == 1
    assert len(audit_log.calls) == 1
    assert audit_log.calls[0]["action"] == "approve"

    # parent dispense status recomputed
    dispense = next(d for d in fake_session.db["pharmacy_dispenses"] if d["id"] == dispense_id)
    assert dispense["status"] == DispenseStatus.DISPENSED


async def test_reject_touches_no_stock_and_marks_rejected(fake_session, audit_log):
    item_row_id, dispense_id = str(uuid.uuid4()), str(uuid.uuid4())
    prescription_id = uuid.uuid4()
    substitute_item_id = uuid.uuid4()
    batch_id = uuid.uuid4()

    _seed_pending_item(
        fake_session, item_row_id=item_row_id, dispense_id=dispense_id,
        prescription_id=prescription_id, prescription_item_id=uuid.uuid4(),
        substitute_item_id=substitute_item_id, quantity_prescribed="5",
    )
    _seed_batch(fake_session, batch_id, substitute_item_id, "20")

    result = await approve_substitution(
        fake_session, SubstitutionApprovalRequest(approved=False, rejection_reason="Not equivalent"),
        item_row_id=item_row_id, approving_user_id=uuid.uuid4(), facility_id=uuid.uuid4(),
    )

    assert result.approval_status == "rejected"
    assert result.quantity_dispensed == Decimal("0")
    assert fake_session.db["inventory_batches"][str(batch_id)]["quantity"] == Decimal("20")
    assert fake_session.db["stock_ledger"] == []
    assert len(audit_log.calls) == 1
    assert audit_log.calls[0]["action"] == "reject"


async def test_approve_already_resolved_item_raises_409(fake_session, audit_log):
    item_row_id, dispense_id = str(uuid.uuid4()), str(uuid.uuid4())
    prescription_id = uuid.uuid4()

    _seed_pending_item(
        fake_session, item_row_id=item_row_id, dispense_id=dispense_id,
        prescription_id=prescription_id, prescription_item_id=uuid.uuid4(),
        substitute_item_id=uuid.uuid4(), quantity_prescribed="5",
    )
    # Already resolved by a prior call
    for r in fake_session.db["pharmacy_dispense_items"]:
        if r["id"] == item_row_id:
            r["approval_status"] = "approved"

    with pytest.raises(HTTPException) as exc_info:
        await approve_substitution(
            fake_session, SubstitutionApprovalRequest(approved=True),
            item_row_id=item_row_id, approving_user_id=uuid.uuid4(), facility_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "not_pending"


async def test_approve_with_no_single_batch_covering_quantity_raises_422(fake_session, audit_log):
    item_row_id, dispense_id = str(uuid.uuid4()), str(uuid.uuid4())
    prescription_id = uuid.uuid4()
    substitute_item_id = uuid.uuid4()
    # Two small batches, neither alone covers 10 — approval doesn't split.
    batch_a, batch_b = uuid.uuid4(), uuid.uuid4()

    _seed_pending_item(
        fake_session, item_row_id=item_row_id, dispense_id=dispense_id,
        prescription_id=prescription_id, prescription_item_id=uuid.uuid4(),
        substitute_item_id=substitute_item_id, quantity_prescribed="10",
    )
    _seed_batch(fake_session, batch_a, substitute_item_id, "4", batch_number="A")
    _seed_batch(fake_session, batch_b, substitute_item_id, "4", batch_number="B")

    with pytest.raises(HTTPException) as exc_info:
        await approve_substitution(
            fake_session, SubstitutionApprovalRequest(approved=True),
            item_row_id=item_row_id, approving_user_id=uuid.uuid4(), facility_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "insufficient_stock_or_no_single_batch"
    # nothing touched
    assert fake_session.db["inventory_batches"][str(batch_a)]["quantity"] == Decimal("4")
    assert fake_session.db["inventory_batches"][str(batch_b)]["quantity"] == Decimal("4")
    assert audit_log.calls == []

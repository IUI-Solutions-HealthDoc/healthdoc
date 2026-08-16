from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

import app.pharmacy.service as pharmacy_service
from app.common.enums import DispenseStatus
from app.pharmacy.schemas import DispenseCreate, DispenseItemCreate, SubstitutionApprovalRequest
from app.pharmacy.service import (
    approve_substitution,
    create_dispense,
    get_prescription_queue,
    search_medicines,
)


@pytest.mark.asyncio
async def test_queue_query_runs_against_postgres(db_session, pharmacy_seed):
    result = await get_prescription_queue(
        db_session,
        facility_id=pharmacy_seed["facility_id"],
        department_id=pharmacy_seed["department_id"],
        status=None,
        page=1,
        page_size=20,
    )
    assert result.total == 1
    assert result.items[0].prescription_id == pharmacy_seed["prescription_id"]


@pytest.mark.asyncio
async def test_search_query_runs_against_postgres_and_orders_fefo(db_session, pharmacy_seed):
    results = await search_medicines(
        db_session, q="paracetamol", facility_id=pharmacy_seed["facility_id"]
    )
    assert len(results) == 1
    assert [batch.batch_number for batch in results[0].batches] == ["EARLY", "LATE"]


@pytest.mark.asyncio
async def test_dispense_uses_ledger_trigger_and_writes_audit(db_session, pharmacy_seed):
    result = await create_dispense(
        db_session,
        DispenseCreate(
            prescription_id=pharmacy_seed["prescription_id"],
            items=[DispenseItemCreate(
                prescription_item_id=pharmacy_seed["prescription_item_id"],
                quantity_dispensed=Decimal("10"),
            )],
        ),
        current_user_id=pharmacy_seed["pharmacist_id"],
        facility_id=pharmacy_seed["facility_id"],
    )
    assert result.status == DispenseStatus.DISPENSED
    quantity = (await db_session.execute(text(
        "SELECT quantity FROM inventory_batches WHERE id = :id"
    ), {"id": pharmacy_seed["early_batch_id"]})).scalar_one()
    assert quantity == Decimal("0")
    ledger_count = (await db_session.execute(text(
        "SELECT count(*) FROM stock_ledger WHERE reference_id = :id"
    ), {"id": result.id})).scalar_one()
    assert ledger_count == 2
    audit_count = (await db_session.execute(text(
        "SELECT count(*) FROM audit_logs WHERE resource_id = :id"
    ), {"id": result.id})).scalar_one()
    assert audit_count == 1


@pytest.mark.asyncio
async def test_insufficient_stock_is_atomic(db_session, pharmacy_seed):
    async def _count(table: str) -> int:
        return (await db_session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()

    # Snapshot rather than assert zero. These were absolute counts, which held
    # only while nothing else in the fixture produced audit rows; most models
    # now opt into auto-auditing via __audit_resource_type__, so the seed alone
    # writes to audit_logs. Comparing before/after tests what this actually
    # cares about — that the failed dispense wrote nothing — and keeps working
    # however much the fixture grows.
    before = {t: await _count(t)
              for t in ("pharmacy_dispenses", "stock_ledger", "audit_logs")}

    with pytest.raises(HTTPException) as exc_info:
        await create_dispense(
            db_session,
            DispenseCreate(
                prescription_id=pharmacy_seed["prescription_id"],
                items=[DispenseItemCreate(
                    prescription_item_id=pharmacy_seed["prescription_item_id"],
                    quantity_dispensed=Decimal("100"),
                )],
            ),
            current_user_id=pharmacy_seed["pharmacist_id"],
            facility_id=pharmacy_seed["facility_id"],
        )
    assert exc_info.value.status_code == 422
    for table, count_before in before.items():
        assert await _count(table) == count_before, (
            f"{table} changed — the failed dispense was not atomic"
        )


@pytest.mark.asyncio
async def test_substitution_approval_debits_split_batches_and_recomputes_status(
    db_session, pharmacy_seed, monkeypatch
):
    async def suppress_unavailable_notification(*args, **kwargs):
        return None

    monkeypatch.setattr(
        pharmacy_service, "_notify_substitution_stakeholders", suppress_unavailable_notification
    )
    pending = await create_dispense(
        db_session,
        DispenseCreate(
            prescription_id=pharmacy_seed["prescription_id"],
            items=[DispenseItemCreate(
                prescription_item_id=pharmacy_seed["prescription_item_id"],
                quantity_dispensed=Decimal("10"),
                substitute_item_id=pharmacy_seed["medicine_id"],
                substitute_reason="Test substitution approval",
            )],
        ),
        current_user_id=pharmacy_seed["pharmacist_id"],
        facility_id=pharmacy_seed["facility_id"],
    )
    pending_item_id = (await db_session.execute(text(
        "SELECT id FROM pharmacy_dispense_items WHERE dispense_id = :id"
    ), {"id": pending.id})).scalar_one()

    approved = await approve_substitution(
        db_session,
        SubstitutionApprovalRequest(approved=True),
        item_row_id=pending_item_id,
        approving_user_id=pharmacy_seed["doctor_id"],
        facility_id=pharmacy_seed["facility_id"],
    )

    assert approved.quantity_dispensed == Decimal("10")
    assert len(approved.batches) == 2
    assert approved.batches[0].batch_id == pharmacy_seed["early_batch_id"]
    assert approved.batches[1].batch_id == pharmacy_seed["late_batch_id"]
    assert approved.approval_status == "approved"
    status = (await db_session.execute(text(
        "SELECT status FROM pharmacy_dispenses WHERE id = :id"
    ), {"id": pending.id})).scalar_one()
    assert status == DispenseStatus.DISPENSED
    ledger_count = (await db_session.execute(text(
        "SELECT count(*) FROM stock_ledger WHERE reference_id = :id"
    ), {"id": pending.id})).scalar_one()
    assert ledger_count == 2


@pytest.mark.asyncio
async def test_substitution_notification_is_persisted(db_session, pharmacy_seed):
    await create_dispense(
        db_session,
        DispenseCreate(
            prescription_id=pharmacy_seed["prescription_id"],
            items=[DispenseItemCreate(
                prescription_item_id=pharmacy_seed["prescription_item_id"],
                quantity_dispensed=Decimal("5"),
                substitute_item_id=pharmacy_seed["medicine_id"],
                substitute_reason="Test substitution",
            )],
        ),
        current_user_id=pharmacy_seed["pharmacist_id"],
        facility_id=pharmacy_seed["facility_id"],
    )
    notification_count = (await db_session.execute(text(
        "SELECT count(*) FROM notification_history WHERE event_type = 'pharmacy_substitution'"
    ))).scalar_one()
    assert notification_count == 1

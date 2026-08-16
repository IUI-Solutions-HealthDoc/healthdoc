from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.pharmacy.schemas import (
    AdjustmentApprovalRequest,
    AdjustmentCreate,
    GrnCreate,
    GrnItemCreate,
    GrnVerifyRequest,
    IndentApprovalRequest,
    IndentCreate,
    IndentItemCreate,
)
from app.pharmacy.service import (
    approve_adjustment,
    approve_indent,
    create_adjustment,
    create_grn,
    create_indent,
    get_reorder_alerts,
    issue_indent,
    verify_grn,
)


@pytest.mark.asyncio
async def test_grn_create_and_verify_writes_batch_and_ledger(db_session, inventory_seed):
    grn = await create_grn(
        db_session,
        GrnCreate(
            supplier_id=inventory_seed["supplier_id"],
            invoice_number="INV-001",
            received_date=date.today(),
            items=[
                GrnItemCreate(
                    item_id=inventory_seed["medicine_id"],
                    batch_number="GRN-BATCH-1",
                    expiry_date=date.today() + timedelta(days=200),
                    quantity=Decimal("50"),
                    unit_price=Decimal("2.50"),
                )
            ],
        ),
        current_user_id=inventory_seed["pharmacist_id"],
        facility_id=inventory_seed["facility_id"],
    )
    assert grn.status == "draft"

    verified = await verify_grn(
        db_session, grn.id,
        GrnVerifyRequest(stock_location_id=inventory_seed["location_id"]),
        current_user_id=inventory_seed["pharmacist_id"],
        facility_id=inventory_seed["facility_id"],
    )
    assert verified.status == "verified"

    batch_row = (
        await db_session.execute(
            text(
                "SELECT quantity FROM inventory_batches WHERE item_id = :item_id "
                "AND batch_number = 'GRN-BATCH-1'"
            ),
            {"item_id": str(inventory_seed["medicine_id"])},
        )
    ).mappings().first()
    assert batch_row["quantity"] == Decimal("50")

    ledger_row = (
        await db_session.execute(
            text(
                "SELECT quantity, transaction_type FROM stock_ledger "
                "WHERE reference_type = 'grn' AND reference_id = :grn_id"
            ),
            {"grn_id": str(grn.id)},
        )
    ).mappings().first()
    assert ledger_row["transaction_type"] == "purchase"
    assert ledger_row["quantity"] == Decimal("50")


@pytest.mark.asyncio
async def test_indent_approve_rejects_wrong_department_hod(db_session, inventory_seed):
    indent = await create_indent(
        db_session,
        IndentCreate(
            department_id=inventory_seed["department_id"],
            items=[IndentItemCreate(item_id=inventory_seed["medicine_id"], quantity_requested=Decimal("3"))],
        ),
        current_user_id=inventory_seed["pharmacist_id"],
        facility_id=inventory_seed["facility_id"],
    )
    assert indent.status == "requested"

    with pytest.raises(HTTPException) as exc:
        await approve_indent(
            db_session, indent.id, IndentApprovalRequest(approve=True),
            current_user_id=inventory_seed["other_hod_id"],
            facility_id=inventory_seed["facility_id"],
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_indent_full_lifecycle_approve_and_issue_deducts_fefo(db_session, inventory_seed):
    indent = await create_indent(
        db_session,
        IndentCreate(
            department_id=inventory_seed["department_id"],
            items=[IndentItemCreate(item_id=inventory_seed["medicine_id"], quantity_requested=Decimal("4"))],
        ),
        current_user_id=inventory_seed["pharmacist_id"],
        facility_id=inventory_seed["facility_id"],
    )

    approved = await approve_indent(
        db_session, indent.id, IndentApprovalRequest(approve=True),
        current_user_id=inventory_seed["hod_id"],
        facility_id=inventory_seed["facility_id"],
    )
    assert approved.status == "approved"

    issued = await issue_indent(
        db_session, indent.id,
        current_user_id=inventory_seed["pharmacist_id"],
        facility_id=inventory_seed["facility_id"],
    )
    assert issued.status == "issued"

    early_batch_row = (
        await db_session.execute(
            text("SELECT quantity FROM inventory_batches WHERE id = :id"),
            {"id": str(inventory_seed["early_batch_id"])},
        )
    ).mappings().first()
    # early batch started at 6, FEFO should have taken from it first (4 of the 4 requested)
    assert early_batch_row["quantity"] == Decimal("2")


@pytest.mark.asyncio
async def test_issue_indent_fails_when_not_approved(db_session, inventory_seed):
    indent = await create_indent(
        db_session,
        IndentCreate(
            department_id=inventory_seed["department_id"],
            items=[IndentItemCreate(item_id=inventory_seed["medicine_id"], quantity_requested=Decimal("1"))],
        ),
        current_user_id=inventory_seed["pharmacist_id"],
        facility_id=inventory_seed["facility_id"],
    )
    with pytest.raises(HTTPException) as exc:
        await issue_indent(
            db_session, indent.id,
            current_user_id=inventory_seed["pharmacist_id"],
            facility_id=inventory_seed["facility_id"],
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_reorder_alerts_flags_items_at_or_below_threshold(db_session, inventory_seed):
    await db_session.execute(
        text(
            "UPDATE inventory_items SET reorder_level = 100 WHERE id = :id"
        ),
        {"id": str(inventory_seed["medicine_id"])},
    )
    alerts = await get_reorder_alerts(db_session, facility_id=inventory_seed["facility_id"])
    flagged_ids = [a.item_id for a in alerts.items]
    assert inventory_seed["medicine_id"] in flagged_ids


@pytest.mark.asyncio
async def test_adjustment_requires_different_second_approver(db_session, inventory_seed):
    adjustment = await create_adjustment(
        db_session,
        AdjustmentCreate(
            item_id=inventory_seed["medicine_id"],
            batch_id=inventory_seed["early_batch_id"],
            quantity_change=Decimal("-2"),
            reason="Damaged in transit",
            first_approver_id=inventory_seed["hod_id"],
        ),
        current_user_id=inventory_seed["pharmacist_id"],
        facility_id=inventory_seed["facility_id"],
    )
    assert adjustment.status == "pending"

    # creator cannot also be the second approver
    with pytest.raises(HTTPException) as exc:
        await approve_adjustment(
            db_session, adjustment.id, AdjustmentApprovalRequest(approve=True),
            current_user_id=inventory_seed["pharmacist_id"],
            facility_id=inventory_seed["facility_id"],
        )
    assert exc.value.status_code == 403

    # designated first approver cannot also be the second approver
    with pytest.raises(HTTPException) as exc:
        await approve_adjustment(
            db_session, adjustment.id, AdjustmentApprovalRequest(approve=True),
            current_user_id=inventory_seed["hod_id"],
            facility_id=inventory_seed["facility_id"],
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_adjustment_approval_by_different_user_updates_stock(db_session, inventory_seed):
    before = (
        await db_session.execute(
            text("SELECT quantity FROM inventory_batches WHERE id = :id"),
            {"id": str(inventory_seed["early_batch_id"])},
        )
    ).mappings().first()

    adjustment = await create_adjustment(
        db_session,
        AdjustmentCreate(
            item_id=inventory_seed["medicine_id"],
            batch_id=inventory_seed["early_batch_id"],
            quantity_change=Decimal("-1"),
            reason="Count correction",
            first_approver_id=inventory_seed["hod_id"],
        ),
        current_user_id=inventory_seed["pharmacist_id"],
        facility_id=inventory_seed["facility_id"],
    )

    approved = await approve_adjustment(
        db_session, adjustment.id, AdjustmentApprovalRequest(approve=True),
        current_user_id=inventory_seed["second_pharmacist_id"],
        facility_id=inventory_seed["facility_id"],
    )
    assert approved.status == "approved"

    after = (
        await db_session.execute(
            text("SELECT quantity FROM inventory_batches WHERE id = :id"),
            {"id": str(inventory_seed["early_batch_id"])},
        )
    ).mappings().first()
    assert after["quantity"] == before["quantity"] - Decimal("1")

    ledger_row = (
        await db_session.execute(
            text(
                "SELECT transaction_type FROM stock_ledger "
                "WHERE reference_type = 'adjustments' AND reference_id = :id"
            ),
            {"id": str(adjustment.id)},
        )
    ).mappings().first()
    assert ledger_row["transaction_type"] == "adjustment"


@pytest.mark.asyncio
async def test_adjustment_rejection_does_not_touch_stock(db_session, inventory_seed):
    before = (
        await db_session.execute(
            text("SELECT quantity FROM inventory_batches WHERE id = :id"),
            {"id": str(inventory_seed["late_batch_id"])},
        )
    ).mappings().first()

    adjustment = await create_adjustment(
        db_session,
        AdjustmentCreate(
            item_id=inventory_seed["medicine_id"],
            batch_id=inventory_seed["late_batch_id"],
            quantity_change=Decimal("-5"),
            reason="Suspected miscount",
            first_approver_id=inventory_seed["hod_id"],
        ),
        current_user_id=inventory_seed["pharmacist_id"],
        facility_id=inventory_seed["facility_id"],
    )

    rejected = await approve_adjustment(
        db_session, adjustment.id, AdjustmentApprovalRequest(approve=False, reason="Not verified"),
        current_user_id=inventory_seed["second_pharmacist_id"],
        facility_id=inventory_seed["facility_id"],
    )
    assert rejected.status == "rejected"

    after = (
        await db_session.execute(
            text("SELECT quantity FROM inventory_batches WHERE id = :id"),
            {"id": str(inventory_seed["late_batch_id"])},
        )
    ).mappings().first()
    assert after["quantity"] == before["quantity"]

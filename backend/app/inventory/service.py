from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.common.patient_scope import facility_today
from app.inventory.schemas import (
    PurchaseOrderCreate,
    PurchaseOrderItemOut,
    PurchaseOrderListOut,
    PurchaseOrderOut,
    PurchaseOrderTransition,
    StockTransferAction,
    StockTransferCreate,
    StockTransferItemOut,
    StockTransferListOut,
    StockTransferOut,
)


async def _purchase_order_out(
    db: AsyncSession, purchase_order_id: UUID, facility_id: UUID
) -> PurchaseOrderOut:
    row = (
        await db.execute(
            text("""
                SELECT po.id, po.po_number, po.supplier_id, s.name AS supplier_name,
                       po.status, po.approved_by, po.expected_date,
                       po.created_at, po.updated_at
                FROM purchase_orders po
                JOIN suppliers s ON s.id = po.supplier_id
                WHERE po.id = :id AND po.facility_id = :facility_id
            """),
            {"id": str(purchase_order_id), "facility_id": str(facility_id)},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    items = (
        await db.execute(
            text("""
                SELECT poi.id, poi.item_id, ii.name AS item_name, poi.quantity,
                       poi.unit_price,
                       COALESCE(SUM(CASE WHEN g.status = 'verified'
                           THEN gi.quantity ELSE 0 END), 0) AS received_quantity
                FROM purchase_order_items poi
                JOIN inventory_items ii ON ii.id = poi.item_id
                LEFT JOIN grn g ON g.purchase_order_id = poi.purchase_order_id
                LEFT JOIN grn_items gi ON gi.grn_id = g.id AND gi.item_id = poi.item_id
                WHERE poi.purchase_order_id = :id
                GROUP BY poi.id, ii.name
                ORDER BY poi.created_at, poi.id
            """),
            {"id": str(purchase_order_id)},
        )
    ).mappings().all()
    return PurchaseOrderOut(
        **dict(row), items=[PurchaseOrderItemOut(**dict(item)) for item in items]
    )


async def create_purchase_order(
    db: AsyncSession,
    payload: PurchaseOrderCreate,
    *,
    facility_id: UUID,
    actor_id: UUID,
) -> PurchaseOrderOut:
    supplier = (
        await db.execute(
            text("""
                SELECT id FROM suppliers
                WHERE id = :id AND facility_id = :facility_id AND is_active = true
            """),
            {"id": str(payload.supplier_id), "facility_id": str(facility_id)},
        )
    ).first()
    if supplier is None:
        raise HTTPException(status_code=404, detail="Active supplier not found")

    for item in payload.items:
        valid_item = (
            await db.execute(
                text("""
                    SELECT ii.id
                    FROM inventory_items ii
                    LEFT JOIN departments d ON d.id = ii.owning_department_id
                    WHERE ii.id = :id AND ii.is_active = true
                      AND (ii.owning_department_id IS NULL OR d.facility_id = :facility_id)
                """),
                {"id": str(item.item_id), "facility_id": str(facility_id)},
            )
        ).first()
        if valid_item is None:
            raise HTTPException(status_code=404, detail=f"Active item {item.item_id} not found")

    purchase_order_id = uuid4()
    po_number = f"PO-{await facility_today(db, facility_id):%Y%m%d}-{uuid4().hex[:10].upper()}"
    await db.execute(
        text("""
            INSERT INTO purchase_orders
                (id, po_number, supplier_id, status, expected_date, facility_id,
                 created_by, updated_by)
            VALUES
                (:id, :po_number, :supplier_id, 'draft', :expected_date,
                 :facility_id, :actor_id, :actor_id)
        """),
        {
            "id": str(purchase_order_id),
            "po_number": po_number,
            "supplier_id": str(payload.supplier_id),
            "expected_date": payload.expected_date,
            "facility_id": str(facility_id),
            "actor_id": str(actor_id),
        },
    )
    for item in payload.items:
        await db.execute(
            text("""
                INSERT INTO purchase_order_items
                    (id, purchase_order_id, item_id, quantity, unit_price)
                VALUES (:id, :purchase_order_id, :item_id, :quantity, :unit_price)
            """),
            {
                "id": str(uuid4()),
                "purchase_order_id": str(purchase_order_id),
                "item_id": str(item.item_id),
                "quantity": item.quantity,
                "unit_price": item.unit_price,
            },
        )
    await write_audit_log(
        db,
        facility_id=facility_id,
        user_id=actor_id,
        action="create",
        resource_type="purchase_orders",
        resource_id=purchase_order_id,
        new_value={"po_number": po_number, "line_count": len(payload.items)},
    )
    return await _purchase_order_out(db, purchase_order_id, facility_id)


async def transition_purchase_order(
    db: AsyncSession,
    purchase_order_id: UUID,
    payload: PurchaseOrderTransition,
    *,
    facility_id: UUID,
    actor_id: UUID,
) -> PurchaseOrderOut:
    row = (
        await db.execute(
            text("""
                SELECT id, status FROM purchase_orders
                WHERE id = :id AND facility_id = :facility_id FOR UPDATE
            """),
            {"id": str(purchase_order_id), "facility_id": str(facility_id)},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    allowed = {
        "draft": {"approved", "cancelled"},
        "approved": {"sent", "cancelled"},
        "sent": {"cancelled"},
    }
    target = payload.target_status
    if target not in allowed.get(row["status"], set()):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot transition purchase order from '{row['status']}' to '{target}'",
        )
    if target == "cancelled":
        receipt_count = (
            await db.execute(
                text("""
                    SELECT count(*) FROM grn
                    WHERE purchase_order_id = :id AND status = 'verified'
                """),
                {"id": str(purchase_order_id)},
            )
        ).scalar_one()
        if receipt_count:
            raise HTTPException(status_code=409, detail="Cannot cancel a purchase order with receipts")
    await db.execute(
        text("""
            UPDATE purchase_orders
            SET status = :status,
                approved_by = COALESCE(CAST(:approved_by AS uuid), approved_by),
                updated_by = :actor_id, updated_at = now()
            WHERE id = :id
        """),
        {
            "status": target,
            "approved_by": str(actor_id) if target == "approved" else None,
            "actor_id": str(actor_id),
            "id": str(purchase_order_id),
        },
    )
    await write_audit_log(
        db,
        facility_id=facility_id,
        user_id=actor_id,
        action="update",
        resource_type="purchase_orders",
        resource_id=purchase_order_id,
        old_value={"status": row["status"]},
        new_value={"status": target},
    )
    return await _purchase_order_out(db, purchase_order_id, facility_id)


async def get_purchase_order(
    db: AsyncSession, purchase_order_id: UUID, *, facility_id: UUID
) -> PurchaseOrderOut:
    return await _purchase_order_out(db, purchase_order_id, facility_id)


async def list_purchase_orders(
    db: AsyncSession,
    *,
    facility_id: UUID,
    status: str | None,
    page: int,
    page_size: int,
) -> PurchaseOrderListOut:
    params = {"facility_id": str(facility_id), "status": status}
    total = (
        await db.execute(
            text("""
                SELECT count(*) FROM purchase_orders
                WHERE facility_id = :facility_id
                  AND (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
            """),
            params,
        )
    ).scalar_one()
    ids = (
        await db.execute(
            text("""
                SELECT id FROM purchase_orders
                WHERE facility_id = :facility_id
                  AND (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
                ORDER BY created_at DESC, id DESC
                LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        )
    ).scalars().all()
    return PurchaseOrderListOut(
        items=[await _purchase_order_out(db, item_id, facility_id) for item_id in ids],
        page=page,
        page_size=page_size,
        total=total,
    )


async def _stock_transfer_out(
    db: AsyncSession, transfer_id: UUID, facility_id: UUID
) -> StockTransferOut:
    row = (
        await db.execute(
            text("""
                SELECT st.id, st.from_location_id, source.name AS from_location_name,
                       st.to_location_id, destination.name AS to_location_name,
                       st.status, st.created_by, st.created_at, st.updated_at
                FROM stock_transfers st
                JOIN stock_locations source ON source.id = st.from_location_id
                JOIN stock_locations destination ON destination.id = st.to_location_id
                WHERE st.id = :id AND source.facility_id = :facility_id
                  AND destination.facility_id = :facility_id
            """),
            {"id": str(transfer_id), "facility_id": str(facility_id)},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Stock transfer not found")
    items = (
        await db.execute(
            text("""
                SELECT sti.id, sti.item_id, ii.name AS item_name, sti.batch_id,
                       ib.batch_number, sti.quantity
                FROM stock_transfer_items sti
                JOIN inventory_items ii ON ii.id = sti.item_id
                JOIN inventory_batches ib ON ib.id = sti.batch_id
                WHERE sti.stock_transfer_id = :id
                ORDER BY sti.created_at, sti.id
            """),
            {"id": str(transfer_id)},
        )
    ).mappings().all()
    return StockTransferOut(
        **dict(row), items=[StockTransferItemOut(**dict(item)) for item in items]
    )


async def create_stock_transfer(
    db: AsyncSession,
    payload: StockTransferCreate,
    *,
    facility_id: UUID,
    actor_id: UUID,
) -> StockTransferOut:
    location_count = (
        await db.execute(
            text("""
                SELECT count(*) FROM stock_locations
                WHERE id IN (:source_id, :destination_id) AND facility_id = :facility_id
            """),
            {
                "source_id": str(payload.from_location_id),
                "destination_id": str(payload.to_location_id),
                "facility_id": str(facility_id),
            },
        )
    ).scalar_one()
    if location_count != 2:
        raise HTTPException(status_code=404, detail="Stock location not found")
    for item in payload.items:
        batch = (
            await db.execute(
                text("""
                    SELECT ib.id FROM inventory_batches ib
                    WHERE ib.id = :batch_id AND ib.item_id = :item_id
                      AND ib.stock_location_id = :source_id
                """),
                {
                    "batch_id": str(item.batch_id),
                    "item_id": str(item.item_id),
                    "source_id": str(payload.from_location_id),
                },
            )
        ).first()
        if batch is None:
            raise HTTPException(status_code=404, detail=f"Source batch {item.batch_id} not found")
    transfer_id = uuid4()
    await db.execute(
        text("""
            INSERT INTO stock_transfers
                (id, from_location_id, to_location_id, status, created_by, updated_by)
            VALUES (:id, :source_id, :destination_id, 'requested', :actor_id, :actor_id)
        """),
        {
            "id": str(transfer_id),
            "source_id": str(payload.from_location_id),
            "destination_id": str(payload.to_location_id),
            "actor_id": str(actor_id),
        },
    )
    for item in payload.items:
        await db.execute(
            text("""
                INSERT INTO stock_transfer_items
                    (id, stock_transfer_id, item_id, batch_id, quantity)
                VALUES (:id, :transfer_id, :item_id, :batch_id, :quantity)
            """),
            {
                "id": str(uuid4()),
                "transfer_id": str(transfer_id),
                "item_id": str(item.item_id),
                "batch_id": str(item.batch_id),
                "quantity": item.quantity,
            },
        )
    await write_audit_log(
        db,
        facility_id=facility_id,
        user_id=actor_id,
        action="create",
        resource_type="stock_transfers",
        resource_id=transfer_id,
        new_value={"line_count": len(payload.items)},
    )
    return await _stock_transfer_out(db, transfer_id, facility_id)


async def _lock_transfer(
    db: AsyncSession, transfer_id: UUID, facility_id: UUID
):
    row = (
        await db.execute(
            text("""
                SELECT st.id, st.from_location_id, st.to_location_id, st.status
                FROM stock_transfers st
                JOIN stock_locations source ON source.id = st.from_location_id
                JOIN stock_locations destination ON destination.id = st.to_location_id
                WHERE st.id = :id AND source.facility_id = :facility_id
                  AND destination.facility_id = :facility_id
                FOR UPDATE OF st
            """),
            {"id": str(transfer_id), "facility_id": str(facility_id)},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Stock transfer not found")
    return row


async def dispatch_stock_transfer(
    db: AsyncSession,
    transfer_id: UUID,
    payload: StockTransferAction,
    *,
    facility_id: UUID,
    actor_id: UUID,
) -> StockTransferOut:
    transfer = await _lock_transfer(db, transfer_id, facility_id)
    if transfer["status"] != "requested":
        raise HTTPException(status_code=409, detail="Only requested transfers can be dispatched")
    items = (
        await db.execute(
            text("""
                SELECT sti.batch_id, sti.item_id, sti.quantity,
                       ib.quantity AS on_hand, ib.reserved_quantity
                FROM stock_transfer_items sti
                JOIN inventory_batches ib ON ib.id = sti.batch_id
                WHERE sti.stock_transfer_id = :id
                ORDER BY sti.batch_id
                FOR UPDATE OF ib
            """),
            {"id": str(transfer_id)},
        )
    ).mappings().all()
    for item in items:
        available = item["on_hand"] - item["reserved_quantity"]
        if available < item["quantity"]:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient available stock for batch {item['batch_id']}",
            )
        await db.execute(
            text("""
                UPDATE inventory_batches
                SET reserved_quantity = reserved_quantity + :quantity, updated_at = now()
                WHERE id = :id
            """),
            {"quantity": item["quantity"], "id": str(item["batch_id"])},
        )
    await db.execute(
        text("""
            UPDATE stock_transfers SET status = 'in_transit', updated_by = :actor_id,
                updated_at = now() WHERE id = :id
        """),
        {"actor_id": str(actor_id), "id": str(transfer_id)},
    )
    await write_audit_log(
        db,
        facility_id=facility_id,
        user_id=actor_id,
        action="dispatch",
        resource_type="stock_transfers",
        resource_id=transfer_id,
        old_value={"status": "requested"},
        new_value={"status": "in_transit", "reason": payload.reason},
    )
    return await _stock_transfer_out(db, transfer_id, facility_id)


async def receive_stock_transfer(
    db: AsyncSession,
    transfer_id: UUID,
    payload: StockTransferAction,
    *,
    facility_id: UUID,
    actor_id: UUID,
) -> StockTransferOut:
    transfer = await _lock_transfer(db, transfer_id, facility_id)
    if transfer["status"] != "in_transit":
        raise HTTPException(status_code=409, detail="Only in-transit transfers can be received")
    items = (
        await db.execute(
            text("""
                SELECT sti.batch_id, sti.item_id, sti.quantity, ib.batch_number,
                       ib.expiry_date, ib.purchase_rate, ib.issue_rate_mrp,
                       ib.quantity AS on_hand, ib.reserved_quantity
                FROM stock_transfer_items sti
                JOIN inventory_batches ib ON ib.id = sti.batch_id
                WHERE sti.stock_transfer_id = :id
                ORDER BY sti.batch_id
                FOR UPDATE OF ib
            """),
            {"id": str(transfer_id)},
        )
    ).mappings().all()
    for item in items:
        if item["reserved_quantity"] < item["quantity"] or item["on_hand"] < item["quantity"]:
            raise HTTPException(status_code=409, detail="Reserved transfer stock is unavailable")
        await db.execute(
            text("""
                UPDATE inventory_batches
                SET reserved_quantity = reserved_quantity - :quantity, updated_at = now()
                WHERE id = :id
            """),
            {"quantity": item["quantity"], "id": str(item["batch_id"])},
        )
        destination_batch_id = uuid4()
        await db.execute(
            text("""
                INSERT INTO inventory_batches
                    (id, item_id, batch_number, expiry_date, quantity, reserved_quantity,
                     purchase_rate, issue_rate_mrp, stock_location_id)
                VALUES
                    (:id, :item_id, :batch_number, :expiry_date, 0, 0,
                     :purchase_rate, :issue_rate_mrp, :location_id)
                ON CONFLICT (item_id, batch_number, stock_location_id) DO NOTHING
            """),
            {
                "id": str(destination_batch_id),
                "item_id": str(item["item_id"]),
                "batch_number": item["batch_number"],
                "expiry_date": item["expiry_date"],
                "purchase_rate": item["purchase_rate"],
                "issue_rate_mrp": item["issue_rate_mrp"],
                "location_id": str(transfer["to_location_id"]),
            },
        )
        destination_batch = (
            await db.execute(
                text("""
                    SELECT id, expiry_date FROM inventory_batches
                    WHERE item_id = :item_id AND batch_number = :batch_number
                      AND stock_location_id = :location_id FOR UPDATE
                """),
                {
                    "item_id": str(item["item_id"]),
                    "batch_number": item["batch_number"],
                    "location_id": str(transfer["to_location_id"]),
                },
            )
        ).mappings().one()
        if destination_batch["expiry_date"] != item["expiry_date"]:
            raise HTTPException(
                status_code=409,
                detail="Destination batch metadata conflicts with the source batch",
            )
        destination_batch_id = destination_batch["id"]
        for batch_id, quantity in (
            (item["batch_id"], -item["quantity"]),
            (destination_batch_id, item["quantity"]),
        ):
            await db.execute(
                text("""
                    INSERT INTO stock_ledger
                        (id, item_id, batch_id, transaction_type, quantity,
                         reference_type, reference_id, performed_by, reason)
                    VALUES
                        (:id, :item_id, :batch_id, 'transfer', :quantity,
                         'stock_transfer', :transfer_id, :actor_id, :reason)
                """),
                {
                    "id": str(uuid4()),
                    "item_id": str(item["item_id"]),
                    "batch_id": str(batch_id),
                    "quantity": quantity,
                    "transfer_id": str(transfer_id),
                    "actor_id": str(actor_id),
                    "reason": payload.reason,
                },
            )
    await db.execute(
        text("""
            UPDATE stock_transfers SET status = 'received', updated_by = :actor_id,
                updated_at = now() WHERE id = :id
        """),
        {"actor_id": str(actor_id), "id": str(transfer_id)},
    )
    await write_audit_log(
        db,
        facility_id=facility_id,
        user_id=actor_id,
        action="receive",
        resource_type="stock_transfers",
        resource_id=transfer_id,
        old_value={"status": "in_transit"},
        new_value={"status": "received", "reason": payload.reason},
    )
    return await _stock_transfer_out(db, transfer_id, facility_id)


async def cancel_stock_transfer(
    db: AsyncSession,
    transfer_id: UUID,
    payload: StockTransferAction,
    *,
    facility_id: UUID,
    actor_id: UUID,
) -> StockTransferOut:
    transfer = await _lock_transfer(db, transfer_id, facility_id)
    if transfer["status"] not in {"requested", "in_transit"}:
        raise HTTPException(status_code=409, detail="Transfer cannot be cancelled")
    if transfer["status"] == "in_transit":
        items = (
            await db.execute(
                text("""
                    SELECT sti.batch_id, sti.quantity
                    FROM stock_transfer_items sti
                    JOIN inventory_batches ib ON ib.id = sti.batch_id
                    WHERE sti.stock_transfer_id = :id
                    ORDER BY sti.batch_id FOR UPDATE OF ib
                """),
                {"id": str(transfer_id)},
            )
        ).mappings().all()
        for item in items:
            result = await db.execute(
                text("""
                    UPDATE inventory_batches
                    SET reserved_quantity = reserved_quantity - :quantity, updated_at = now()
                    WHERE id = :id AND reserved_quantity >= :quantity
                """),
                {"quantity": item["quantity"], "id": str(item["batch_id"])},
            )
            if result.rowcount != 1:
                raise HTTPException(status_code=409, detail="Transfer reservation is inconsistent")
    await db.execute(
        text("""
            UPDATE stock_transfers SET status = 'cancelled', updated_by = :actor_id,
                updated_at = now() WHERE id = :id
        """),
        {"actor_id": str(actor_id), "id": str(transfer_id)},
    )
    await write_audit_log(
        db,
        facility_id=facility_id,
        user_id=actor_id,
        action="update",
        resource_type="stock_transfers",
        resource_id=transfer_id,
        old_value={"status": transfer["status"]},
        new_value={"status": "cancelled", "reason": payload.reason},
    )
    return await _stock_transfer_out(db, transfer_id, facility_id)


async def get_stock_transfer(
    db: AsyncSession, transfer_id: UUID, *, facility_id: UUID
) -> StockTransferOut:
    return await _stock_transfer_out(db, transfer_id, facility_id)


async def list_stock_transfers(
    db: AsyncSession,
    *,
    facility_id: UUID,
    status: str | None,
    page: int,
    page_size: int,
) -> StockTransferListOut:
    params = {"facility_id": str(facility_id), "status": status}
    scope = """
        FROM stock_transfers st
        JOIN stock_locations source ON source.id = st.from_location_id
        JOIN stock_locations destination ON destination.id = st.to_location_id
        WHERE source.facility_id = :facility_id AND destination.facility_id = :facility_id
          AND (CAST(:status AS text) IS NULL OR st.status = CAST(:status AS text))
    """
    total = (await db.execute(text("SELECT count(*) " + scope), params)).scalar_one()
    ids = (
        await db.execute(
            text(
                "SELECT st.id " + scope
                + " ORDER BY st.created_at DESC, st.id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        )
    ).scalars().all()
    return StockTransferListOut(
        items=[await _stock_transfer_out(db, item_id, facility_id) for item_id in ids],
        page=page,
        page_size=page_size,
        total=total,
    )

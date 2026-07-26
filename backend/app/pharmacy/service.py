from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.common.enums import DispenseStatus
from app.pharmacy.schemas import (
    BatchAvailability,
    DispenseCreate,
    DispenseItemOut,
    DispenseOut,
    MedicineSearchResult,
    PrescriptionQueueItem,
    PrescriptionQueueResponse,
)


async def get_prescription_queue(
    db: AsyncSession,
    *,
    facility_id: UUID,
    department_id: UUID | None,
    status: str | None,
    page: int,
    page_size: int,
) -> PrescriptionQueueResponse:
    """Prescriptions awaiting or in dispense, newest first."""
    page_size = min(page_size, 100)
    offset = (page - 1) * page_size

    where = ["p.facility_id = :facility_id"]
    params: dict = {"facility_id": str(facility_id), "limit": page_size, "offset": offset}

    if department_id is not None:
        where.append("e.department_id = :department_id")
        params["department_id"] = str(department_id)

    if status is not None:
        where.append("pd.status = :status")
        params["status"] = status
    elif status is None:
        where.append("(pd.status IS NULL OR pd.status NOT IN ('dispensed', 'cancelled'))")

    where_clause = " AND ".join(where)

    count_sql = text(f"""
        SELECT count(*)
        FROM prescriptions p
        JOIN encounters e ON e.id = p.encounter_id
        LEFT JOIN LATERAL (
            SELECT status FROM pharmacy_dispenses
            WHERE prescription_id = p.id AND is_current
            LIMIT 1
        ) pd ON true
        WHERE {where_clause}
    """)
    total = (await db.execute(count_sql, params)).scalar_one()

    rows_sql = text(f"""
        SELECT
            p.id AS prescription_id,
            p.patient_id,
            pt.full_name AS patient_full_name,
            pt.uhid,
            pt.thid,
            e.visit_id,
            p.encounter_id,
            p.created_at AS prescribed_at,
            (SELECT count(*) FROM prescription_items pi WHERE pi.prescription_id = p.id) AS item_count,
            pd.status AS dispense_status
        FROM prescriptions p
        JOIN encounters e ON e.id = p.encounter_id
        JOIN patients pt ON pt.id = p.patient_id
        LEFT JOIN LATERAL (
            SELECT status FROM pharmacy_dispenses
            WHERE prescription_id = p.id AND is_current
            LIMIT 1
        ) pd ON true
        WHERE {where_clause}
        ORDER BY p.created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    rows = (await db.execute(rows_sql, params)).mappings().all()

    items = [PrescriptionQueueItem(**dict(row)) for row in rows]
    return PrescriptionQueueResponse(items=items, page=page, page_size=page_size, total=total)


async def search_medicines(
    db: AsyncSession, *, q: str, facility_id: UUID, limit: int = 20
) -> list[MedicineSearchResult]:
    """FEFO-ordered (earliest expiry first) in-stock batches per medicine."""
    items_sql = text("""
        SELECT id, name, generic_name, strength, form, is_controlled_drug
        FROM inventory_items
        WHERE item_type = 'medicine'
          AND is_active
          AND (name ILIKE :pattern OR generic_name ILIKE :pattern)
        ORDER BY name
        LIMIT :limit
    """)
    item_rows = (
        await db.execute(items_sql, {"pattern": f"%{q}%", "limit": limit})
    ).mappings().all()
    if not item_rows:
        return []

    item_ids = [row["id"] for row in item_rows]

    batches_sql = text("""
        SELECT ib.item_id, ib.id AS batch_id, ib.batch_number, ib.expiry_date,
               ib.quantity, ib.stock_location_id, ib.issue_rate_mrp
        FROM inventory_batches ib
        JOIN stock_locations sl ON sl.id = ib.stock_location_id
        WHERE ib.item_id = ANY(:item_ids)
          AND ib.quantity > 0
          AND sl.facility_id = :facility_id
        ORDER BY ib.item_id, ib.expiry_date ASC
    """)
    batch_rows = (
        await db.execute(batches_sql, {"item_ids": item_ids, "facility_id": str(facility_id)})
    ).mappings().all()

    batches_by_item: dict = {}
    for b in batch_rows:
        batches_by_item.setdefault(b["item_id"], []).append(
            BatchAvailability(
                batch_id=b["batch_id"],
                batch_number=b["batch_number"],
                expiry_date=b["expiry_date"].isoformat(),
                quantity=b["quantity"],
                stock_location_id=b["stock_location_id"],
                issue_rate_mrp=b["issue_rate_mrp"],
            )
        )

    results = []
    for row in item_rows:
        item_batches = batches_by_item.get(row["id"], [])
        results.append(
            MedicineSearchResult(
                item_id=row["id"],
                name=row["name"],
                generic_name=row["generic_name"],
                strength=row["strength"],
                form=row["form"],
                is_controlled_drug=row["is_controlled_drug"],
                total_available_quantity=sum(
                    (b.quantity for b in item_batches), Decimal("0")
                ),
                batches=item_batches,
            )
        )
    return results


async def create_dispense(
    db: AsyncSession,
    payload: DispenseCreate,
    *,
    current_user_id: UUID,
    facility_id: UUID,
) -> DispenseOut:
    
    presc_row = (
        await db.execute(
            text("SELECT id, patient_id, encounter_id FROM prescriptions WHERE id = :id"),
            {"id": str(payload.prescription_id)},
        )
    ).mappings().first()
    if presc_row is None:
        raise HTTPException(status_code=404, detail="Prescription not found")

    for item in payload.items:
        batch = (
            await db.execute(
                text("SELECT id, quantity FROM inventory_batches WHERE id = :id FOR UPDATE"),
                {"id": str(item.batch_id)},
            )
        ).mappings().first()
        if batch is None:
            raise HTTPException(status_code=404, detail=f"Batch {item.batch_id} not found")
        if batch["quantity"] < item.quantity_dispensed:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "insufficient_stock",
                    "batch_id": str(item.batch_id),
                    "available": str(batch["quantity"]),
                    "requested": str(item.quantity_dispensed),
                },
            )

    next_version = (
        await db.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM pharmacy_dispenses "
                "WHERE prescription_id = :id"
            ),
            {"id": str(payload.prescription_id)},
        )
    ).scalar_one()

    await db.execute(
        text(
            "UPDATE pharmacy_dispenses SET is_current = false "
            "WHERE prescription_id = :id AND is_current"
        ),
        {"id": str(payload.prescription_id)},
    )

    dispense_id = str(uuid4())
    await db.execute(
        text("""
            INSERT INTO pharmacy_dispenses
                (id, prescription_id, status, dispensed_by, version, is_current)
            VALUES
                (:id, :prescription_id, :status, :dispensed_by, :version, true)
        """),
        {
            "id": dispense_id,
            "prescription_id": str(payload.prescription_id),
            "status": DispenseStatus.DISPENSED,
            "dispensed_by": str(current_user_id),
            "version": next_version,
        },
    )

    items_out: list[DispenseItemOut] = []
    for item in payload.items:
        item_id = str(uuid4())
        await db.execute(
            text("""
                INSERT INTO pharmacy_dispense_items
                    (id, dispense_id, prescription_item_id, batch_id,
                     quantity_dispensed, is_substitute, substitute_reason)
                VALUES
                    (:id, :dispense_id, :prescription_item_id, :batch_id,
                     :quantity_dispensed, :is_substitute, :substitute_reason)
            """),
            {
                "id": item_id,
                "dispense_id": dispense_id,
                "prescription_item_id": str(item.prescription_item_id),
                "batch_id": str(item.batch_id),
                "quantity_dispensed": item.quantity_dispensed,
                "is_substitute": item.is_substitute,
                "substitute_reason": item.substitute_reason,
            },
        )

        await db.execute(
            text(
                "UPDATE inventory_batches SET quantity = quantity - :qty, "
                "updated_at = now() WHERE id = :id"
            ),
            {"qty": item.quantity_dispensed, "id": str(item.batch_id)},
        )

        await db.execute(
            text("""
                INSERT INTO stock_ledger
                    (id, item_id, batch_id, transaction_type, quantity,
                     reference_type, reference_id, performed_by)
                SELECT :ledger_id, ib.item_id, ib.id, 'issue', :neg_qty,
                       'pharmacy_dispense', :dispense_id, :performed_by
                FROM inventory_batches ib WHERE ib.id = :batch_id
            """),
            {
                "ledger_id": str(uuid4()),
                "neg_qty": -item.quantity_dispensed,
                "dispense_id": dispense_id,
                "performed_by": str(current_user_id),
                "batch_id": str(item.batch_id),
            },
        )

        items_out.append(
            DispenseItemOut(
                id=item_id,
                prescription_item_id=item.prescription_item_id,
                batch_id=item.batch_id,
                quantity_dispensed=item.quantity_dispensed,
                is_substitute=item.is_substitute,
                substitute_reason=item.substitute_reason,
            )
        )

    # AUDIT — written in the same transaction as the mutation
    await write_audit_log(
        db,
        facility_id=facility_id,
        user_id=current_user_id,
        action="create",
        resource_type="pharmacy_dispenses",
        resource_id=dispense_id,
        patient_id=presc_row["patient_id"],
        new_value={"prescription_id": str(payload.prescription_id), "version": next_version},
    )

    return DispenseOut(
        id=dispense_id,
        prescription_id=payload.prescription_id,
        visit_id=None,
        status=DispenseStatus.DISPENSED,
        dispensed_by=current_user_id,
        version=next_version,
        is_current=True,
        created_at=(
            await db.execute(
                text("SELECT created_at FROM pharmacy_dispenses WHERE id = :id"),
                {"id": dispense_id},
            )
        ).scalar_one(),
        items=items_out,
    )

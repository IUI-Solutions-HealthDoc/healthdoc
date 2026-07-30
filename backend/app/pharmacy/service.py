from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.common.enums import DispenseStatus, NotificationStatus
from app.pharmacy.schemas import (
    BatchAllocation,
    BatchAvailability,
    DispenseCreate,
    DispenseItemOut,
    DispenseOut,
    MedicineSearchResult,
    PrescriptionQueueItem,
    PrescriptionQueueResponse,
    SubstitutionApprovalRequest,
)

# ---------------------------------------------------------------------------
# Prescription queue
# ---------------------------------------------------------------------------

async def get_prescription_queue(
    db: AsyncSession,
    *,
    facility_id: UUID,
    department_id: UUID | None,
    status: str | None,
    page: int,
    page_size: int,
) -> PrescriptionQueueResponse:
    
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
        # default view: exclude fully dispensed/cancelled prescriptions
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


# ---------------------------------------------------------------------------
# Medicine search — FEFO batch ordering
# ---------------------------------------------------------------------------

async def search_medicines(
    db: AsyncSession, *, q: str, facility_id: UUID, limit: int = 20
) -> list[MedicineSearchResult]:
    """Trigram/prefix search over medicine names, each with its FEFO-ordered
    (earliest expiry first) in-stock batches at this facility's locations.
    """
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


# Dispense creation 
 

class BatchAllocationResult:
    """Internal — one (batch, quantity) slice picked during FEFO allocation."""
    __slots__ = ("batch_id", "batch_number", "expiry_date", "quantity")

    def __init__(self, batch_id, batch_number, expiry_date, quantity):
        self.batch_id = batch_id
        self.batch_number = batch_number
        self.expiry_date = expiry_date
        self.quantity = quantity


async def _fefo_allocate(
    db: AsyncSession, *, item_id: UUID, facility_id: UUID, quantity_needed: Decimal
) -> tuple[list[BatchAllocationResult], Decimal]:
    
   
    candidates_sql = text("""
        SELECT ib.id, ib.batch_number, ib.expiry_date, ib.quantity
        FROM inventory_batches ib
        JOIN stock_locations sl ON sl.id = ib.stock_location_id
        WHERE ib.item_id = :item_id
          AND ib.quantity > 0
          AND sl.facility_id = :facility_id
        ORDER BY ib.expiry_date ASC
        FOR UPDATE OF ib
    """)
    candidates = (
        await db.execute(candidates_sql, {"item_id": str(item_id), "facility_id": str(facility_id)})
    ).mappings().all()

    allocations: list[BatchAllocationResult] = []
    remaining = quantity_needed
    for batch in candidates:
        if remaining <= 0:
            break
        take = min(remaining, batch["quantity"])
        allocations.append(
            BatchAllocationResult(
                batch_id=batch["id"],
                batch_number=batch["batch_number"],
                expiry_date=batch["expiry_date"],
                quantity=take,
            )
        )
        remaining -= take

    return allocations, remaining


async def _resolve_medicine_item_id(db: AsyncSession, prescription_item_id: UUID) -> UUID:
    
    row = (
        await db.execute(
            text("SELECT medicine_item_id FROM prescription_items WHERE id = :id"),
            {"id": str(prescription_item_id)},
        )
    ).mappings().first()
    if row is None or row["medicine_item_id"] is None:
        raise HTTPException(
            status_code=404,
            detail=f"prescription_item {prescription_item_id} not found or has no linked medicine",
        )
    return row["medicine_item_id"]


async def _write_notification(
    db: AsyncSession, *, recipient_user_id: UUID, notification_type: str,
    title: str, body: str, reference_type: str, reference_id: str,
) -> None:
    
    try:
        await db.execute(
            text("""
                INSERT INTO notifications
                    (id, recipient_user_id, notification_type, title, body,
                     status, reference_type, reference_id)
                VALUES
                    (:id, :recipient_user_id, :notification_type, :title, :body,
                     :status, :reference_type, :reference_id)
            """),
            {
                "id": str(uuid4()), "recipient_user_id": str(recipient_user_id),
                "notification_type": notification_type, "title": title, "body": body,
                "status": NotificationStatus.QUEUED, "reference_type": reference_type,
                "reference_id": reference_id,
            },
        )
    except Exception:  
        pass


async def _notify_substitution_stakeholders(
    db: AsyncSession, *, prescription_id: UUID, title: str, body: str, reference_id: str,
) -> None:
    
    row = (
        await db.execute(
            text("""
                SELECT e.provider_id AS doctor_id, p.patient_id
                FROM prescriptions p
                JOIN encounters e ON e.id = p.encounter_id
                WHERE p.id = :id
            """),
            {"id": str(prescription_id)},
        )
    ).mappings().first()
    if row is None:
        return

    if row.get("doctor_id"):
        await _write_notification(
            db, recipient_user_id=row["doctor_id"], notification_type="pharmacy_substitution",
            title=title, body=body, reference_type="pharmacy_dispense_items",
            reference_id=reference_id,
        )
    if row.get("patient_id"):
        await _write_notification(
            db, recipient_user_id=row["patient_id"], notification_type="pharmacy_substitution",
            title=title, body=body, reference_type="pharmacy_dispense_items",
            reference_id=reference_id,
        )


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

    plan: list[dict] = []
    for item in payload.items:
        if item.substitute_item_id is not None:
            plan.append({
                "kind": "substitution",
                "prescription_item_id": item.prescription_item_id,
                "requested_qty": item.quantity_dispensed,
                "fulfilled_qty": Decimal("0"),
                "allocations": [],
                "substitute_item_id": item.substitute_item_id,
                "substitute_reason": item.substitute_reason,
            })
            continue

        if item.batch_id is not None:
            
            batch = (
                await db.execute(
                    text("SELECT id, batch_number, expiry_date, quantity "
                         "FROM inventory_batches WHERE id = :id FOR UPDATE"),
                    {"id": str(item.batch_id)},
                )
            ).mappings().first()
            if batch is None:
                raise HTTPException(status_code=404, detail=f"Batch {item.batch_id} not found")
            if batch["quantity"] < item.quantity_dispensed:
                if not payload.allow_partial:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "insufficient_stock", "batch_id": str(item.batch_id),
                            "available": str(batch["quantity"]),
                            "requested": str(item.quantity_dispensed),
                        },
                    )
                allocations = [BatchAllocationResult(
                    batch_id=batch["id"], batch_number=batch["batch_number"],
                    expiry_date=batch["expiry_date"], quantity=batch["quantity"],
                )] if batch["quantity"] > 0 else []
            else:
                allocations = [BatchAllocationResult(
                    batch_id=batch["id"], batch_number=batch["batch_number"],
                    expiry_date=batch["expiry_date"], quantity=item.quantity_dispensed,
                )]
        else:
            
            medicine_item_id = await _resolve_medicine_item_id(db, item.prescription_item_id)
            allocations, short = await _fefo_allocate(
                db, item_id=medicine_item_id, facility_id=facility_id,
                quantity_needed=item.quantity_dispensed,
            )
            if short > 0 and not payload.allow_partial:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "insufficient_stock",
                        "prescription_item_id": str(item.prescription_item_id),
                        "requested": str(item.quantity_dispensed), "short_by": str(short),
                    },
                )

        fulfilled_qty = sum((a.quantity for a in allocations), Decimal("0"))
        plan.append({
            "kind": "normal",
            "prescription_item_id": item.prescription_item_id,
            "requested_qty": item.quantity_dispensed,
            "fulfilled_qty": fulfilled_qty,
            "allocations": allocations,
            "substitute_item_id": None,
            "substitute_reason": None,
        })

   
    next_version = (
        await db.execute(
            text("SELECT COALESCE(MAX(version), 0) + 1 FROM pharmacy_dispenses "
                 "WHERE prescription_id = :id"),
            {"id": str(payload.prescription_id)},
        )
    ).scalar_one()

    await db.execute(
        text("UPDATE pharmacy_dispenses SET is_current = false "
             "WHERE prescription_id = :id AND is_current"),
        {"id": str(payload.prescription_id)},
    )

    has_pending_substitution = any(p["kind"] == "substitution" for p in plan)
    non_substitution = [p for p in plan if p["kind"] != "substitution"]
    any_partial_or_empty = any(p["fulfilled_qty"] < p["requested_qty"] for p in non_substitution)

    if has_pending_substitution:
        overall_status = DispenseStatus.DOCTOR_APPROVAL_REQUIRED
    elif non_substitution and all(p["fulfilled_qty"] == 0 for p in non_substitution):
        overall_status = DispenseStatus.OUT_OF_STOCK
    elif any_partial_or_empty:
        overall_status = DispenseStatus.PARTIALLY_DISPENSED
    else:
        overall_status = DispenseStatus.DISPENSED

    dispense_id = str(uuid4())
    await db.execute(
        text("""
            INSERT INTO pharmacy_dispenses
                (id, prescription_id, status, dispensed_by, version, is_current)
            VALUES
                (:id, :prescription_id, :status, :dispensed_by, :version, true)
        """),
        {
            "id": dispense_id, "prescription_id": str(payload.prescription_id),
            "status": overall_status, "dispensed_by": str(current_user_id),
            "version": next_version,
        },
    )

    items_out: list[DispenseItemOut] = []
    for p in plan:
        if p["kind"] == "substitution":
            item_row_id = str(uuid4())
            await db.execute(
                text("""
                    INSERT INTO pharmacy_dispense_items
                        (id, dispense_id, prescription_item_id, batch_id,
                         quantity_prescribed, quantity_dispensed, is_substitute,
                         substitute_item_id, substitute_reason, approval_status)
                    VALUES
                        (:id, :dispense_id, :prescription_item_id, NULL,
                         :quantity_prescribed, NULL, true,
                         :substitute_item_id, :substitute_reason, 'pending')
                """),
                {
                    "id": item_row_id, "dispense_id": dispense_id,
                    "prescription_item_id": str(p["prescription_item_id"]),
                    "quantity_prescribed": p["requested_qty"],
                    "substitute_item_id": str(p["substitute_item_id"]),
                    "substitute_reason": p["substitute_reason"],
                },
            )
            await _notify_substitution_stakeholders(
                db, prescription_id=payload.prescription_id,
                title="Medicine substitution needs your approval",
                body=(
                    f"Pharmacist requested substituting prescription item "
                    f"{p['prescription_item_id']} — reason: {p['substitute_reason'] or 'not given'}"
                ),
                reference_id=item_row_id,
            )
            items_out.append(DispenseItemOut(
                item_row_ids=[item_row_id],
                prescription_item_id=p["prescription_item_id"],
                quantity_prescribed=p["requested_qty"],
                quantity_dispensed=Decimal("0"),
                is_substitute=True,
                substitute_item_id=p["substitute_item_id"],
                substitute_reason=p["substitute_reason"],
                is_partial=True,
                approval_status="pending",
                batches=[],
            ))
            continue

        row_ids: list[UUID] = []
        batch_allocations_out: list[BatchAllocation] = []
        for alloc in p["allocations"]:
            item_row_id = str(uuid4())
            await db.execute(
                text("""
                    INSERT INTO pharmacy_dispense_items
                        (id, dispense_id, prescription_item_id, batch_id,
                         quantity_dispensed, is_substitute, substitute_reason,
                         approval_status)
                    VALUES
                        (:id, :dispense_id, :prescription_item_id, :batch_id,
                         :quantity_dispensed, false, NULL, 'not_required')
                """),
                {
                    "id": item_row_id, "dispense_id": dispense_id,
                    "prescription_item_id": str(p["prescription_item_id"]),
                    "batch_id": str(alloc.batch_id), "quantity_dispensed": alloc.quantity,
                },
            )
            await db.execute(
                text("UPDATE inventory_batches SET quantity = quantity - :qty, "
                     "updated_at = now() WHERE id = :id"),
                {"qty": alloc.quantity, "id": str(alloc.batch_id)},
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
                    "ledger_id": str(uuid4()), "neg_qty": -alloc.quantity,
                    "dispense_id": dispense_id, "performed_by": str(current_user_id),
                    "batch_id": str(alloc.batch_id),
                },
            )
            row_ids.append(item_row_id)
            batch_allocations_out.append(BatchAllocation(
                batch_id=alloc.batch_id, batch_number=alloc.batch_number,
                quantity_from_batch=alloc.quantity,
                expiry_date=alloc.expiry_date.isoformat() if hasattr(alloc.expiry_date, "isoformat")
                else str(alloc.expiry_date),
            ))

        items_out.append(DispenseItemOut(
            item_row_ids=row_ids,
            prescription_item_id=p["prescription_item_id"],
            quantity_prescribed=p["requested_qty"],
            quantity_dispensed=p["fulfilled_qty"],
            is_substitute=False,
            substitute_item_id=None,
            substitute_reason=None,
            is_partial=p["fulfilled_qty"] < p["requested_qty"],
            approval_status="not_required",
            batches=batch_allocations_out,
        ))

    await write_audit_log(
        db, facility_id=facility_id, user_id=current_user_id, action="create",
        resource_type="pharmacy_dispenses", resource_id=dispense_id,
        patient_id=presc_row["patient_id"],
        new_value={
            "prescription_id": str(payload.prescription_id), "version": next_version,
            "status": overall_status,
        },
    )

    return DispenseOut(
        id=dispense_id, prescription_id=payload.prescription_id, visit_id=None,
        status=overall_status, dispensed_by=current_user_id, version=next_version,
        is_current=True,
        created_at=(
            await db.execute(
                text("SELECT created_at FROM pharmacy_dispenses WHERE id = :id"),
                {"id": dispense_id},
            )
        ).scalar_one(),
        items=items_out,
    )


async def approve_substitution(
    db: AsyncSession,
    payload: SubstitutionApprovalRequest,
    *,
    item_row_id: UUID,
    approving_user_id: UUID,
    facility_id: UUID,
) -> DispenseItemOut:
    
    item_row = (
        await db.execute(
            text("""
                SELECT pdi.id, pdi.dispense_id, pdi.prescription_item_id,
                       pdi.quantity_prescribed, pdi.substitute_item_id,
                       pdi.approval_status, pd.prescription_id
                FROM pharmacy_dispense_items pdi
                JOIN pharmacy_dispenses pd ON pd.id = pdi.dispense_id
                WHERE pdi.id = :id
            """),
            {"id": str(item_row_id)},
        )
    ).mappings().first()
    if item_row is None:
        raise HTTPException(status_code=404, detail="Dispense item not found")
    if item_row["approval_status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail={"code": "not_pending", "current_status": item_row["approval_status"]},
        )

    if not payload.approved:
        await db.execute(
            text("""
                UPDATE pharmacy_dispense_items
                SET approval_status = 'rejected', approved_by = :approved_by,
                    approved_at = now(), rejection_reason = :reason
                WHERE id = :id
            """),
            {"approved_by": str(approving_user_id), "reason": payload.rejection_reason,
             "id": str(item_row_id)},
        )
        await _recompute_dispense_status(db, item_row["dispense_id"])
        await write_audit_log(
            db, facility_id=facility_id, user_id=approving_user_id, action="reject",
            resource_type="pharmacy_dispense_items", resource_id=str(item_row_id),
            new_value={"rejection_reason": payload.rejection_reason},
        )
        await _notify_substitution_stakeholders(
            db, prescription_id=item_row["prescription_id"],
            title="Substitution rejected",
            body=f"Reason: {payload.rejection_reason or 'not given'}",
            reference_id=str(item_row_id),
        )
        return DispenseItemOut(
            item_row_ids=[item_row_id], prescription_item_id=item_row["prescription_item_id"],
            quantity_prescribed=item_row["quantity_prescribed"], quantity_dispensed=Decimal("0"),
            is_substitute=True, substitute_item_id=item_row["substitute_item_id"],
            substitute_reason=payload.rejection_reason, is_partial=True,
            approval_status="rejected", batches=[],
        )

    allocations, short = await _fefo_allocate(
        db, item_id=item_row["substitute_item_id"], facility_id=facility_id,
        quantity_needed=item_row["quantity_prescribed"],
    )
    if len(allocations) != 1 or short > 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "insufficient_stock_or_no_single_batch",
                "message": "No single batch covers this quantity (or none in stock). "
                "Reject this substitution and ask the pharmacist to retry as a "
                "regular partial-allowed dispense instead.",
                "short_by": str(short),
            },
        )
    alloc = allocations[0]

    await db.execute(
        text("""
            UPDATE pharmacy_dispense_items
            SET batch_id = :batch_id, quantity_dispensed = :qty,
                approval_status = 'approved', approved_by = :approved_by, approved_at = now()
            WHERE id = :id
        """),
        {"batch_id": str(alloc.batch_id), "qty": alloc.quantity,
         "approved_by": str(approving_user_id), "id": str(item_row_id)},
    )
    await db.execute(
        text("UPDATE inventory_batches SET quantity = quantity - :qty, "
             "updated_at = now() WHERE id = :id"),
        {"qty": alloc.quantity, "id": str(alloc.batch_id)},
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
            "ledger_id": str(uuid4()), "neg_qty": -alloc.quantity,
            "dispense_id": item_row["dispense_id"], "performed_by": str(approving_user_id),
            "batch_id": str(alloc.batch_id),
        },
    )

    await _recompute_dispense_status(db, item_row["dispense_id"])
    await write_audit_log(
        db, facility_id=facility_id, user_id=approving_user_id, action="approve",
        resource_type="pharmacy_dispense_items", resource_id=str(item_row_id),
        new_value={"batch_id": str(alloc.batch_id), "quantity_dispensed": str(alloc.quantity)},
    )
    await _notify_substitution_stakeholders(
        db, prescription_id=item_row["prescription_id"], title="Substitution approved",
        body=f"Dispensed {alloc.quantity} from batch {alloc.batch_number}",
        reference_id=str(item_row_id),
    )

    return DispenseItemOut(
        item_row_ids=[item_row_id], prescription_item_id=item_row["prescription_item_id"],
        quantity_prescribed=item_row["quantity_prescribed"], quantity_dispensed=alloc.quantity,
        is_substitute=True, substitute_item_id=item_row["substitute_item_id"],
        substitute_reason=None, is_partial=alloc.quantity < item_row["quantity_prescribed"],
        approval_status="approved",
        batches=[BatchAllocation(
            batch_id=alloc.batch_id, batch_number=alloc.batch_number,
            quantity_from_batch=alloc.quantity,
            expiry_date=alloc.expiry_date.isoformat() if hasattr(alloc.expiry_date, "isoformat")
            else str(alloc.expiry_date),
        )],
    )


async def _recompute_dispense_status(db: AsyncSession, dispense_id: str) -> None:
    """After a substitution is approved/rejected, re-derive the parent
    pharmacy_dispenses.status from all its items' current state."""
    rows = (
        await db.execute(
            text("""
                SELECT approval_status, quantity_prescribed, quantity_dispensed
                FROM pharmacy_dispense_items WHERE dispense_id = :id
            """),
            {"id": str(dispense_id)},
        )
    ).mappings().all()

    if any(r["approval_status"] == "pending" for r in rows):
        new_status = DispenseStatus.DOCTOR_APPROVAL_REQUIRED
    elif all(
        (r["quantity_dispensed"] or Decimal("0")) >= (r["quantity_prescribed"] or Decimal("0"))
        for r in rows
    ):
        new_status = DispenseStatus.DISPENSED
    elif any((r["quantity_dispensed"] or Decimal("0")) > 0 for r in rows):
        new_status = DispenseStatus.PARTIALLY_DISPENSED
    else:
        new_status = DispenseStatus.OUT_OF_STOCK

    await db.execute(
        text("UPDATE pharmacy_dispenses SET status = :status, updated_at = now() WHERE id = :id"),
        {"status": new_status, "id": str(dispense_id)},
    )

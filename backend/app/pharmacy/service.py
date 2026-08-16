from __future__ import annotations

import json
import logging
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.allergies.service import AllergyConflict, check_prescription_item
from app.audit.service import write_audit_log
from app.common.enums import DispenseStatus, NotificationStatus
from app.common.redis import publish_event, stock_alert_channel
from app.pharmacy.interactions import DrugInteractionConflict, check_against_existing
from app.pharmacy.schemas import (
    BatchAllocation,
    BatchAvailability,
    DispenseCreate,
    DispenseItemOut,
    DispenseOut,
    ExpiringBatch,
    ExpiryTrackerResponse,
    MedicineSearchResult,
    PrescriptionQueueItem,
    PrescriptionQueueResponse,
    SubstitutionApprovalRequest,
    GrnCreate,
    GrnItemOut,
    GrnOut,
    GrnVerifyRequest,
    IndentCreate,
    IndentOut,
    IndentItemOut,
    IndentApprovalRequest,
    ReorderAlertItem,
    ReorderAlertsResponse,
    AdjustmentCreate,
    AdjustmentOut,
    AdjustmentApprovalRequest,
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

    where = ["pt.facility_id = :facility_id"]
    params: dict = {"facility_id": str(facility_id), "limit": page_size, "offset": offset}

    if department_id is not None:
        where.append("v.department_id = :department_id")
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
            JOIN visits v ON v.id = e.visit_id
        JOIN patients pt ON pt.id = p.patient_id
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
            JOIN visits v ON v.id = e.visit_id
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
# Medicine search - FEFO batch ordering
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
        JOIN facilities fac ON fac.id = sl.facility_id
        WHERE ib.item_id = ANY(:item_ids)
          AND ib.quantity > 0
          AND sl.facility_id = :facility_id
          AND ib.expiry_date >= (now() AT TIME ZONE fac.timezone)::date
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
    """Internal - one (batch, quantity) slice picked during FEFO allocation."""
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
        JOIN facilities fac ON fac.id = sl.facility_id
        WHERE ib.item_id = :item_id
          AND ib.quantity > 0
          AND sl.facility_id = :facility_id
          AND ib.expiry_date >= (now() AT TIME ZONE fac.timezone)::date
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
    facility_id: UUID,
) -> None:
    """Log a notification-worthy event to notification_history.

    notification_history has no per-recipient/title/body/status columns of
    its own (event_type, payload JSONB, department_id, created_at) - those
    fields are carried inside payload instead of being column-mapped 1:1.
    """
    try:
        await db.execute(
            text("""
                INSERT INTO notification_history
                    (id, event_type, payload, facility_id)
                VALUES
                    (:id, :event_type, CAST(:payload AS jsonb), :facility_id)
            """),
            {
                "id": str(uuid4()),
                "event_type": notification_type,
                "facility_id": str(facility_id),
                "payload": json.dumps({
                    "recipient_user_id": str(recipient_user_id),
                    "title": title,
                    "body": body,
                    "status": NotificationStatus.QUEUED,
                    "reference_type": reference_type,
                    "reference_id": reference_id,
                }),
            },
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "Failed to write notification_history row for %s (recipient=%s, reference=%s/%s)",
            notification_type, recipient_user_id, reference_type, reference_id,
        )

async def _notify_substitution_stakeholders(
    db: AsyncSession, *, prescription_id: UUID, title: str, body: str, reference_id: str,
) -> None:
    
    row = (
    await db.execute(
        text("""
            SELECT e.provider_user_id AS doctor_id,
                   e.facility_id AS facility_id
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
            reference_id=reference_id, facility_id=row["facility_id"],
        )


async def _publish_low_stock_alerts(
    db: AsyncSession, *, facility_id: UUID, plan: list[dict]
) -> None:
    batch_ids: set[str] = set()
    for p in plan:
        for alloc in p.get("allocations", []):
            batch_ids.add(str(alloc.batch_id))
    if not batch_ids:
        return

    rows = (
        await db.execute(
            text("""
                SELECT ii.id AS item_id, ii.name, ii.reorder_level,
                       COALESCE(SUM(ib2.quantity), 0) AS total_remaining
                FROM inventory_items ii
                JOIN inventory_batches ib2 ON ib2.item_id = ii.id
                JOIN stock_locations sl2 ON sl2.id = ib2.stock_location_id
                WHERE ii.id IN (
                    SELECT DISTINCT ib.item_id FROM inventory_batches ib
                    WHERE ib.id = ANY(:batch_ids)
                ) AND sl2.facility_id = :facility_id
                GROUP BY ii.id, ii.name, ii.reorder_level
            """),
            {"batch_ids": list(batch_ids), "facility_id": str(facility_id)},
        )
    ).mappings().all()
    for r in rows:
        if r["total_remaining"] > r["reorder_level"]:
            continue
        event_type = "low_stock" if r["total_remaining"] > 0 else "out_of_stock"
        payload = {
            "item_id": str(r["item_id"]),
            "item_name": r["name"],
            "total_remaining": str(r["total_remaining"]),
            "reorder_level": str(r["reorder_level"]),
        }
        await db.execute(
            text("""
                INSERT INTO notification_history
                    (id, event_type, payload, department_id, facility_id, created_at)
                SELECT uuid_generate_v4(), :event_type, CAST(:payload AS jsonb),
                       ii.owning_department_id, :facility_id, now()
                FROM inventory_items ii WHERE ii.id = :item_id
            """),
            {"event_type": event_type, "payload": json.dumps(payload),
             "item_id": str(r["item_id"]), "facility_id": str(facility_id)},
        )
        await publish_event(stock_alert_channel(facility_id), event_type, payload)


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

    _checked_ingredient_codes: list[str] = []
    for item in payload.items:
        target_item_id = item.substitute_item_id
        if target_item_id is None:
            row = (
                await db.execute(
                    text("""
                        SELECT ii.ingredient_code
                        FROM prescription_items pi
                        JOIN inventory_items ii ON ii.id = pi.medicine_item_id
                        WHERE pi.id = :id
                    """),
                    {"id": str(item.prescription_item_id)},
                )
            ).mappings().first()
        else:
            row = (
                await db.execute(
                    text("SELECT ingredient_code FROM inventory_items WHERE id = :id"),
                    {"id": str(target_item_id)},
                )
            ).mappings().first()
        ingredient_code = row["ingredient_code"] if row else None

        try:
            await check_prescription_item(
                db,
                patient_id=presc_row["patient_id"],
                ingredient_code=ingredient_code,
                override_reason=item.allergy_override_reason,
            )
        except AllergyConflict as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "allergy_conflict",
                    "prescription_item_id": str(item.prescription_item_id),
                    "substance": exc.allergy.substance_text,
                    "severity": exc.allergy.severity,
                    "absolute": exc.absolute,
                    "reaction": exc.allergy.reaction,
                },
            ) from exc

        try:
            await check_against_existing(
                db,
                new_ingredient_code=ingredient_code,
                existing_ingredient_codes=_checked_ingredient_codes,
                override_reason=item.interaction_override_reason,
            )
        except DrugInteractionConflict as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "drug_interaction_conflict",
                    "prescription_item_id": str(item.prescription_item_id),
                    "ingredient_a": exc.interaction.ingredient_code_a,
                    "ingredient_b": exc.interaction.ingredient_code_b,
                    "severity": exc.interaction.severity,
                    "absolute": exc.absolute,
                    "description": exc.interaction.description,
                },
            ) from exc

        if ingredient_code is not None:
            _checked_ingredient_codes.append(ingredient_code)

    plan: list[dict] = []
    # Track quantity already claimed against each explicitly-pinned batch_id
    # within THIS request, before hitting the DB again. Two items pointing at
    # the same batch_id would otherwise each check against the batch's raw
    # DB quantity independently, both pass, and the combined UPDATE later
    # drives quantity negative -- caught only by ck_inventory_batches_quantity
    # as a raw constraint error instead of a clean 422.
    reserved_by_batch: dict[str, Decimal] = {}

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
                    text("""
                        SELECT ib.id, ib.batch_number, ib.expiry_date, ib.quantity,
                               ib.expiry_date >= (now() AT TIME ZONE fac.timezone)::date AS not_expired
                        FROM inventory_batches ib
                        JOIN stock_locations sl ON sl.id = ib.stock_location_id
                        JOIN facilities fac ON fac.id = sl.facility_id
                        WHERE ib.id = :id AND sl.facility_id = :facility_id
                        FOR UPDATE OF ib
                    """),
                    {"id": str(item.batch_id), "facility_id": str(facility_id)},
                )
            ).mappings().first()
            if batch is None:
                raise HTTPException(status_code=404, detail=f"Batch {item.batch_id} not found")
            if not batch["not_expired"]:
                if not (item.expiry_override and item.expiry_override_reason):
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "batch_expired",
                            "batch_id": str(item.batch_id),
                            "expiry_date": batch["expiry_date"].isoformat(),
                        },
                    )
            already_reserved = reserved_by_batch.get(str(item.batch_id), Decimal("0"))
            available_now = batch["quantity"] - already_reserved

            if available_now < item.quantity_dispensed:
                if not payload.allow_partial:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "insufficient_stock", "batch_id": str(item.batch_id),
                            "available": str(available_now),
                            "requested": str(item.quantity_dispensed),
                        },
                    )
                allocated_qty = max(available_now, Decimal("0"))
                allocations = [BatchAllocationResult(
                    batch_id=batch["id"], batch_number=batch["batch_number"],
                    expiry_date=batch["expiry_date"], quantity=allocated_qty,
                )] if allocated_qty > 0 else []
            else:
                allocated_qty = item.quantity_dispensed
                allocations = [BatchAllocationResult(
                    batch_id=batch["id"], batch_number=batch["batch_number"],
                    expiry_date=batch["expiry_date"], quantity=allocated_qty,
                )]

            reserved_by_batch[str(item.batch_id)] = already_reserved + allocated_qty
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
            "expiry_override_by": (
                current_user_id if item.batch_id is not None and item.expiry_override else None
            ),
            "expiry_override_reason": (
                item.expiry_override_reason
                if item.batch_id is not None and item.expiry_override else None
            ),
        })

    # Lock the prescription row first so two concurrent dispenses for the same
    # prescription can't both read the same MAX(version) and both try to
    # insert it (uq_pharmacy_dispenses_prescription_id_version then rejects
    # the second with a raw 500 instead of a clean, serialized version bump).
    await db.execute(
        text("SELECT id FROM prescriptions WHERE id = :id FOR UPDATE"),
        {"id": str(payload.prescription_id)},
    )
    # pr-check: ignore - MAX()+1 is safe HERE and only here, because the
    # SELECT ... FOR UPDATE above already serialises every concurrent dispense
    # for this prescription. Two callers cannot both read the same MAX.
    #
    # Same exception as queue/service.py:202, and the same caveat: do NOT copy
    # this pattern anywhere the parent row isn't already locked. Where no
    # single row lock covers the scope - accession numbers, receipt numbers -
    # use a counters row instead (app/common/accession.py, billing_counters).
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
                    f"{p['prescription_item_id']} - reason: {p['substitute_reason'] or 'not given'}"
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
                         quantity_prescribed, quantity_dispensed, is_substitute,
                         substitute_reason, approval_status,
                         expiry_override_by, expiry_override_reason)
                    VALUES
                        (:id, :dispense_id, :prescription_item_id, :batch_id,
                         :quantity_prescribed, :quantity_dispensed, false, NULL,
                         'not_required', :expiry_override_by, :expiry_override_reason)
                """),
                {
                    "id": item_row_id, "dispense_id": dispense_id,
                    "prescription_item_id": str(p["prescription_item_id"]),
                    "batch_id": str(alloc.batch_id),
                    "quantity_prescribed": p["requested_qty"],
                    "quantity_dispensed": alloc.quantity,
                    "expiry_override_by": (
                        str(p["expiry_override_by"]) if p["expiry_override_by"] else None
                    ),
                    "expiry_override_reason": p["expiry_override_reason"],
                },
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

    overrides = [
        {
            "prescription_item_id": str(i.prescription_item_id),
            "allergy_override_reason": i.allergy_override_reason,
            "interaction_override_reason": i.interaction_override_reason,
        }
        for i in payload.items
        if i.allergy_override_reason or i.interaction_override_reason
    ]

    await write_audit_log(
        db, facility_id=facility_id, user_id=current_user_id, action="create",
        resource_type="pharmacy_dispenses", resource_id=UUID(dispense_id),
        patient_id=presc_row["patient_id"],
        new_value={
            "prescription_id": str(payload.prescription_id), "version": next_version,
            "status": overall_status,
            "overrides": overrides if overrides else None,
        },
    )

    await _publish_low_stock_alerts(db, facility_id=facility_id, plan=plan)

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
                       pdi.quantity_prescribed, pdi.substitute_item_id, pdi.substitute_reason,
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
            resource_type="pharmacy_dispense_items", resource_id=item_row_id,
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
    if short > 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "insufficient_stock",
                "message": "Not enough stock across all batches to cover this substitution. "
                "Reject and ask the pharmacist to retry as a regular partial-allowed "
                "dispense instead.",
                "short_by": str(short),
            },
        )

    # Split across as many batches as _fefo_allocate needed (previously this
    # rejected anything requiring more than one batch, even though the
    # underlying allocator has always supported splitting). The first
    # allocation reuses the existing pending row; any further allocations
    # get their own new pharmacy_dispense_items rows sharing the same
    # dispense_id/prescription_item_id, matching the pattern already used
    # for normal (non-substitution) FEFO-split items.
    item_row_ids: list[UUID] = []
    batches_out: list[BatchAllocation] = []
    total_dispensed = Decimal("0")

    for i, alloc in enumerate(allocations):
        if i == 0:
            row_id = item_row_id
            await db.execute(
                text("""
                    UPDATE pharmacy_dispense_items
                    SET batch_id = :batch_id, quantity_dispensed = :qty,
                        approval_status = 'approved', approved_by = :approved_by, approved_at = now()
                    WHERE id = :id
                """),
                {"batch_id": str(alloc.batch_id), "qty": alloc.quantity,
                 "approved_by": str(approving_user_id), "id": str(row_id)},
            )
        else:
            row_id = uuid4()
            await db.execute(
                text("""
                    INSERT INTO pharmacy_dispense_items
                        (id, dispense_id, prescription_item_id, batch_id,
                         quantity_dispensed, is_substitute, substitute_item_id,
                         substitute_reason, approval_status, approved_by, approved_at)
                    VALUES
                        (:id, :dispense_id, :prescription_item_id, :batch_id,
                         :quantity_dispensed, true, :substitute_item_id,
                         :substitute_reason, 'approved', :approved_by, now())
                """),
                {
                    "id": str(row_id), "dispense_id": item_row["dispense_id"],
                    "prescription_item_id": str(item_row["prescription_item_id"]),
                    "batch_id": str(alloc.batch_id), "quantity_dispensed": alloc.quantity,
                    "substitute_item_id": str(item_row["substitute_item_id"]),
                    "substitute_reason": item_row["substitute_reason"],
                    "approved_by": str(approving_user_id),
                },
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

        item_row_ids.append(row_id)
        total_dispensed += alloc.quantity
        batches_out.append(BatchAllocation(
            batch_id=alloc.batch_id, batch_number=alloc.batch_number,
            quantity_from_batch=alloc.quantity,
            expiry_date=alloc.expiry_date.isoformat() if hasattr(alloc.expiry_date, "isoformat")
            else str(alloc.expiry_date),
        ))

    await _recompute_dispense_status(db, item_row["dispense_id"])
    await write_audit_log(
        db, facility_id=facility_id, user_id=approving_user_id, action="approve",
        resource_type="pharmacy_dispense_items", resource_id=item_row_id,
        new_value={
            "batches": [
                {"batch_id": str(b.batch_id), "quantity": str(b.quantity_from_batch)}
                for b in batches_out
            ],
            "total_dispensed": str(total_dispensed),
        },
    )
    await _notify_substitution_stakeholders(
        db, prescription_id=item_row["prescription_id"], title="Substitution approved",
        body=f"Dispensed {total_dispensed} across {len(batches_out)} batch"
             f"{'es' if len(batches_out) != 1 else ''}",
        reference_id=str(item_row_id),
    )

    return DispenseItemOut(
        item_row_ids=item_row_ids, prescription_item_id=item_row["prescription_item_id"],
        quantity_prescribed=item_row["quantity_prescribed"], quantity_dispensed=total_dispensed,
        is_substitute=True, substitute_item_id=item_row["substitute_item_id"],
        substitute_reason=None, is_partial=total_dispensed < item_row["quantity_prescribed"],
        approval_status="approved",
        batches=batches_out,
    )


async def _recompute_dispense_status(db: AsyncSession, dispense_id: str) -> None:
    """After a substitution is approved/rejected, re-derive the parent
    pharmacy_dispenses.status from all its items' current state.

    Aggregated per prescription_item_id, not per row: a FEFO split across
    several batches produces multiple pharmacy_dispense_items rows for the
    same prescription item, each carrying the item's full quantity_prescribed.
    Comparing quantity_dispensed >= quantity_prescribed row-by-row would flag
    a fully-fulfilled split item as partial (e.g. 6+4 dispensed against 10
    prescribed reads as two rows of "6 >= 10" and "4 >= 10", both false).
    """
    rows = (
        await db.execute(
            text("""
                SELECT approval_status, prescription_item_id,
                       quantity_prescribed, quantity_dispensed
                FROM pharmacy_dispense_items WHERE dispense_id = :id
            """),
            {"id": str(dispense_id)},
        )
    ).mappings().all()

    by_item: dict = {}
    for r in rows:
        agg = by_item.setdefault(
            r["prescription_item_id"], {"prescribed": Decimal("0"), "dispensed": Decimal("0")}
        )
        agg["prescribed"] = max(agg["prescribed"], r["quantity_prescribed"] or Decimal("0"))
        agg["dispensed"] += r["quantity_dispensed"] or Decimal("0")

    if any(r["approval_status"] == "pending" for r in rows):
        new_status = DispenseStatus.DOCTOR_APPROVAL_REQUIRED
    elif all(agg["dispensed"] >= agg["prescribed"] for agg in by_item.values()):
        new_status = DispenseStatus.DISPENSED
    elif any(agg["dispensed"] > 0 for agg in by_item.values()):
        new_status = DispenseStatus.PARTIALLY_DISPENSED
    else:
        new_status = DispenseStatus.OUT_OF_STOCK

    await db.execute(
        text("UPDATE pharmacy_dispenses SET status = :status, updated_at = now() WHERE id = :id"),
        {"status": new_status, "id": str(dispense_id)},
    )

# ---------------------------------------------------------------------------
# Pharmacy MIS report
# ---------------------------------------------------------------------------

from datetime import date as _date
from datetime import timedelta as _timedelta

from app.pharmacy.schemas import PharmacyMisReport as _PharmacyMisReport


async def _facility_business_date(db: AsyncSession, facility_id: UUID) -> _date:
    """Current business date for this facility - schema doc's blanket rule:
    business dates use the facility's IANA timezone, never bare UTC now() or
    CURRENT_DATE. Used only to default date_to/date_from when the caller
    omits them.
    """
    row = (
        await db.execute(
            text("SELECT (now() AT TIME ZONE timezone)::date AS business_date "
                 "FROM facilities WHERE id = :id"),
            {"id": str(facility_id)},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Facility not found")
    return row["business_date"]


async def _facility_timezone(db: AsyncSession, facility_id: UUID) -> str:
    """Facility's IANA timezone string - sibling to _facility_business_date,
    for callers that need the raw timezone to bind as a query param rather
    than a computed business date.
    """
    row = (
        await db.execute(
            text("SELECT timezone FROM facilities WHERE id = :id"),
            {"id": str(facility_id)},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Facility not found")
    return row["timezone"]


async def get_pharmacy_mis_report(
    db: AsyncSession,
    *,
    facility_id: UUID,
    date_from: _date | None,
    date_to: _date | None,
    expiry_window_days: int = 30,
) -> _PharmacyMisReport:
    """
    Read-only aggregate - no mutation, so per app/audit/service.py's own
    manual-path/query-path split this does NOT call write_audit_log().

    fill_rate/turnaround anchor on prescriptions.created_at; stockout/
    substitution counts anchor on pharmacy_dispenses.created_at instead.

    expiring_batches_count/expiring_stock_value are NOT period-scoped -
    always a snapshot as of now, relative to period_end + expiry_window_days.
    """
    resolved_date_to = date_to or await _facility_business_date(db, facility_id)
    resolved_date_from = date_from or (resolved_date_to - _timedelta(days=30))
    if resolved_date_from > resolved_date_to:
        raise HTTPException(422, "date_from must be on or before date_to")

    facility_id_str = str(facility_id)
    tz = await _facility_timezone(db, facility_id)
    params = {
        "facility_id": facility_id_str,
        "date_from": resolved_date_from,
        "date_to": resolved_date_to,
        "tz": tz,
    }

    prescriptions_total = (
        await db.execute(
            text("""
                SELECT count(*)
                FROM prescriptions p
                JOIN patients pt ON pt.id = p.patient_id
                WHERE pt.facility_id = :facility_id
                  AND (p.created_at AT TIME ZONE :tz)::date BETWEEN :date_from AND :date_to
            """),
            params,
        )
    ).scalar_one()

    dispense_stats = (
        await db.execute(
            text("""
                SELECT
                    count(*) AS dispenses_total,
                    count(*) FILTER (WHERE pd.status = :out_of_stock) AS stockout_count,
                    count(*) FILTER (WHERE pd.status = :dispensed) AS dispensed_count
                FROM pharmacy_dispenses pd
                JOIN prescriptions p ON p.id = pd.prescription_id
                JOIN patients pt ON pt.id = p.patient_id
                WHERE pt.facility_id = :facility_id
                  AND (pd.created_at AT TIME ZONE :tz)::date BETWEEN :date_from AND :date_to
            """),
            {**params, "out_of_stock": DispenseStatus.OUT_OF_STOCK, "dispensed": DispenseStatus.DISPENSED},
        )
    ).mappings().one()
    dispenses_total = dispense_stats["dispenses_total"]
    stockout_count = dispense_stats["stockout_count"]
    dispensed_count = dispense_stats["dispensed_count"]

    substitution_count = (
        await db.execute(
            text("""
                SELECT count(*)
                FROM pharmacy_dispense_items pdi
                JOIN pharmacy_dispenses pd ON pd.id = pdi.dispense_id
                JOIN prescriptions p ON p.id = pd.prescription_id
                JOIN patients pt ON pt.id = p.patient_id
                WHERE pt.facility_id = :facility_id
                  AND (pd.created_at AT TIME ZONE :tz)::date BETWEEN :date_from AND :date_to
                  AND pdi.is_substitute
            """),
            params,
        )
    ).scalar_one()

    avg_turnaround_minutes = (
        await db.execute(
            text("""
                SELECT avg(EXTRACT(EPOCH FROM (pd.created_at - p.created_at)) / 60.0)
                FROM pharmacy_dispenses pd
                JOIN prescriptions p ON p.id = pd.prescription_id
                JOIN patients pt ON pt.id = p.patient_id
                WHERE pt.facility_id = :facility_id
                  AND (pd.created_at AT TIME ZONE :tz)::date BETWEEN :date_from AND :date_to
                  AND pd.version = 1
            """),
            params,
        )
    ).scalar_one()

    expiring = (
        await db.execute(
            text("""
                SELECT
                    count(*) AS expiring_batches_count,
                    COALESCE(sum(ib.quantity * COALESCE(ib.issue_rate_mrp, 0)), 0) AS expiring_stock_value
                FROM inventory_batches ib
                JOIN stock_locations sl ON sl.id = ib.stock_location_id
                WHERE sl.facility_id = :facility_id
                  AND ib.quantity > 0
                  AND ib.expiry_date <= (CAST(:date_to AS date) + (interval '1 day' * :window))
            """),
            {"facility_id": facility_id_str, "date_to": resolved_date_to, "window": expiry_window_days},
        )
    ).mappings().one()

    fill_rate_pct = (
        (Decimal(dispensed_count) / Decimal(prescriptions_total) * 100)
        if prescriptions_total > 0 else Decimal("0")
    )
    substitution_rate_pct = (
        (Decimal(substitution_count) / Decimal(dispenses_total) * 100)
        if dispenses_total > 0 else Decimal("0")
    )

    return _PharmacyMisReport(
        facility_id=facility_id,
        period_start=resolved_date_from,
        period_end=resolved_date_to,
        prescriptions_total=prescriptions_total,
        dispenses_total=dispenses_total,
        fill_rate_pct=fill_rate_pct,
        stockout_count=stockout_count,
        substitution_count=substitution_count,
        substitution_rate_pct=substitution_rate_pct,
        avg_turnaround_minutes=(
            Decimal(str(avg_turnaround_minutes)) if avg_turnaround_minutes is not None else None
        ),
        expiring_batches_count=expiring["expiring_batches_count"],
        expiring_stock_value=Decimal(str(expiring["expiring_stock_value"])),
    )


# -- B6-W5-01: GRN --------------------------------------------------------

async def create_grn(
    db: AsyncSession,
    payload: GrnCreate,
    *,
    current_user_id: UUID,
    facility_id: UUID,
) -> GrnOut:
    grn_id = uuid4()
    await db.execute(
        text("""
            INSERT INTO grn
                (id, facility_id, supplier_id, invoice_number, received_date,
                 status, created_by, updated_by)
            VALUES
                (:id, :facility_id, :supplier_id, :invoice_number, :received_date,
                 'draft', :user_id, :user_id)
        """),
        {
            "id": str(grn_id), "facility_id": str(facility_id),
            "supplier_id": str(payload.supplier_id),
            "invoice_number": payload.invoice_number,
            "received_date": payload.received_date,
            "user_id": str(current_user_id),
        },
    )

    items_out: list[GrnItemOut] = []
    for item in payload.items:
        item_id = uuid4()
        await db.execute(
            text("""
                INSERT INTO grn_items
                    (id, grn_id, item_id, batch_number, expiry_date, quantity, unit_price)
                VALUES
                    (:id, :grn_id, :item_id, :batch_number, :expiry_date, :quantity, :unit_price)
            """),
            {
                "id": str(item_id), "grn_id": str(grn_id), "item_id": str(item.item_id),
                "batch_number": item.batch_number, "expiry_date": item.expiry_date,
                "quantity": item.quantity, "unit_price": item.unit_price,
            },
        )
        items_out.append(GrnItemOut(
            id=item_id, item_id=item.item_id, batch_number=item.batch_number,
            expiry_date=item.expiry_date, quantity=item.quantity, unit_price=item.unit_price,
        ))

    await write_audit_log(
        db, facility_id=facility_id, user_id=current_user_id, action="create",
        resource_type="grn", resource_id=grn_id,
        new_value={"supplier_id": str(payload.supplier_id), "item_count": len(items_out)},
    )

    return GrnOut(
        id=grn_id, supplier_id=payload.supplier_id, invoice_number=payload.invoice_number,
        received_date=payload.received_date, status="draft", items=items_out,
    )


async def verify_grn(
    db: AsyncSession,
    grn_id: UUID,
    payload: GrnVerifyRequest,
    *,
    current_user_id: UUID,
    facility_id: UUID,
) -> GrnOut:
    grn_row = (
        await db.execute(
            text("""
                SELECT id, supplier_id, invoice_number, received_date, status
                FROM grn WHERE id = :id AND facility_id = :facility_id FOR UPDATE
            """),
            {"id": str(grn_id), "facility_id": str(facility_id)},
        )
    ).mappings().first()
    if grn_row is None:
        raise HTTPException(status_code=404, detail="GRN not found")
    if grn_row["status"] not in ("draft", "received"):
        raise HTTPException(status_code=409, detail=f"Cannot verify GRN in status '{grn_row['status']}'")

    loc_row = (
        await db.execute(
            text("SELECT id FROM stock_locations WHERE id = :id AND facility_id = :facility_id"),
            {"id": str(payload.stock_location_id), "facility_id": str(facility_id)},
        )
    ).mappings().first()
    if loc_row is None:
        raise HTTPException(status_code=404, detail="Stock location not found for this facility")

    grn_items = (
        await db.execute(
            text("""
                SELECT id, item_id, batch_number, expiry_date, quantity, unit_price
                FROM grn_items WHERE grn_id = :grn_id
            """),
            {"grn_id": str(grn_id)},
        )
    ).mappings().all()
    if not grn_items:
        raise HTTPException(status_code=409, detail="GRN has no items")

    items_out: list[GrnItemOut] = []
    for gi in grn_items:
        existing_batch = (
            await db.execute(
                text("""
                    SELECT id, quantity FROM inventory_batches
                    WHERE item_id = :item_id AND batch_number = :batch_number
                      AND stock_location_id = :loc_id
                    FOR UPDATE
                """),
                {
                    "item_id": str(gi["item_id"]), "batch_number": gi["batch_number"],
                    "loc_id": str(payload.stock_location_id),
                },
            )
        ).mappings().first()

        if existing_batch is not None:
            batch_id = existing_batch["id"]
        else:
            batch_id = uuid4()
            await db.execute(
                text("""
                    INSERT INTO inventory_batches
                        (id, item_id, batch_number, expiry_date, quantity,
                         purchase_rate, stock_location_id)
                    VALUES
                        (:id, :item_id, :batch_number, :expiry_date, 0,
                         :purchase_rate, :loc_id)
                """),
                {
                    "id": str(batch_id), "item_id": str(gi["item_id"]),
                    "batch_number": gi["batch_number"], "expiry_date": gi["expiry_date"],
                    "purchase_rate": gi["unit_price"],
                    "loc_id": str(payload.stock_location_id),
                },
            )

        ledger_id = uuid4()
        await db.execute(
            text("""
                INSERT INTO stock_ledger
                    (id, item_id, batch_id, transaction_type, quantity,
                     reference_type, reference_id, performed_by)
                VALUES
                    (:id, :item_id, :batch_id, 'purchase', :qty,
                     'grn', :grn_id, :user_id)
            """),
            {
                "id": str(ledger_id), "item_id": str(gi["item_id"]), "batch_id": str(batch_id),
                "qty": gi["quantity"], "grn_id": str(grn_id), "user_id": str(current_user_id),
            },
        )

        items_out.append(GrnItemOut(
            id=gi["id"], item_id=gi["item_id"], batch_number=gi["batch_number"],
            expiry_date=gi["expiry_date"], quantity=gi["quantity"], unit_price=gi["unit_price"],
        ))

    await db.execute(
        text("UPDATE grn SET status = 'verified', updated_by = :user_id, "
             "updated_at = now() WHERE id = :id"),
        {"user_id": str(current_user_id), "id": str(grn_id)},
    )

    await write_audit_log(
        db, facility_id=facility_id, user_id=current_user_id, action="verify",
        resource_type="grn", resource_id=grn_id,
        new_value={"stock_location_id": str(payload.stock_location_id), "item_count": len(items_out)},
    )

    return GrnOut(
        id=grn_id, supplier_id=grn_row["supplier_id"], invoice_number=grn_row["invoice_number"],
        received_date=grn_row["received_date"], status="verified", items=items_out,
    )


# -- B6-W5-01: Indents ----------------------------------------------------

async def create_indent(
    db: AsyncSession,
    payload: IndentCreate,
    *,
    current_user_id: UUID,
    facility_id: UUID,
) -> IndentOut:
    dept_row = (
        await db.execute(
            text("SELECT id FROM departments WHERE id = :id AND facility_id = :facility_id"),
            {"id": str(payload.department_id), "facility_id": str(facility_id)},
        )
    ).mappings().first()
    if dept_row is None:
        raise HTTPException(status_code=404, detail="Department not found for this facility")

    indent_id = uuid4()
    await db.execute(
        text("""
            INSERT INTO indents
                (id, facility_id, department_id, status, created_by, updated_by)
            VALUES
                (:id, :facility_id, :department_id, 'requested', :user_id, :user_id)
        """),
        {
            "id": str(indent_id), "facility_id": str(facility_id),
            "department_id": str(payload.department_id), "user_id": str(current_user_id),
        },
    )

    items_out: list[IndentItemOut] = []
    for item in payload.items:
        item_id = uuid4()
        await db.execute(
            text("""
                INSERT INTO indent_items (id, indent_id, item_id, quantity_requested)
                VALUES (:id, :indent_id, :item_id, :quantity_requested)
            """),
            {
                "id": str(item_id), "indent_id": str(indent_id),
                "item_id": str(item.item_id), "quantity_requested": item.quantity_requested,
            },
        )
        items_out.append(IndentItemOut(
            id=item_id, item_id=item.item_id, quantity_requested=item.quantity_requested,
        ))

    await write_audit_log(
        db, facility_id=facility_id, user_id=current_user_id, action="create",
        resource_type="indents", resource_id=indent_id,
        new_value={"department_id": str(payload.department_id), "item_count": len(items_out)},
    )

    return IndentOut(
        id=indent_id, department_id=payload.department_id, status="requested",
        approved_by=None, items=items_out,
    )


async def approve_indent(
    db: AsyncSession,
    indent_id: UUID,
    payload: IndentApprovalRequest,
    *,
    current_user_id: UUID,
    facility_id: UUID,
) -> IndentOut:
    indent_row = (
        await db.execute(
            text("""
                SELECT id, department_id, status, created_by FROM indents
                WHERE id = :id AND facility_id = :facility_id FOR UPDATE
            """),
            {"id": str(indent_id), "facility_id": str(facility_id)},
        )
    ).mappings().first()
    if indent_row is None:
        raise HTTPException(status_code=404, detail="Indent not found")
    if indent_row["status"] != "requested":
        raise HTTPException(
            status_code=409, detail=f"Cannot decide indent in status '{indent_row['status']}'"
        )

    hod_row = (
        await db.execute(
            text("SELECT department_id FROM users WHERE id = :id"),
            {"id": str(current_user_id)},
        )
    ).mappings().first()
    if hod_row is None or hod_row["department_id"] != indent_row["department_id"]:
        raise HTTPException(
            status_code=403, detail="Only the HOD of this indent's own department may decide it"
        )

    # Maker-checker: the requester cannot decide their own indent. A HOD
    # raising an indent for their own department is the normal case, not an
    # edge case, so without this the dual sign-off #219 asks for collapses to
    # one person. Same rule create_adjustment/approve_adjustment already apply
    # below, and the same shape as emergency/service.py's merge approval.
    if indent_row["created_by"] == current_user_id:
        raise HTTPException(
            status_code=409,
            detail={"code": "self_approval_not_allowed",
                    "message": "The requester cannot approve their own indent"},
        )

    new_status = "approved" if payload.approve else "rejected"
    await db.execute(
        text("""
            UPDATE indents SET status = :status, approved_by = :user_id,
                updated_by = :user_id, updated_at = now()
            WHERE id = :id
        """),
        {"status": new_status, "user_id": str(current_user_id), "id": str(indent_id)},
    )

    await write_audit_log(
        db, facility_id=facility_id, user_id=current_user_id,
        action="approve" if payload.approve else "reject",
        resource_type="indents", resource_id=indent_id,
        new_value={"reason": payload.reason},
    )

    items = (
        await db.execute(
            text("SELECT id, item_id, quantity_requested FROM indent_items WHERE indent_id = :id"),
            {"id": str(indent_id)},
        )
    ).mappings().all()
    items_out = [
        IndentItemOut(id=i["id"], item_id=i["item_id"], quantity_requested=i["quantity_requested"])
        for i in items
    ]

    return IndentOut(
        id=indent_id, department_id=indent_row["department_id"], status=new_status,
        approved_by=current_user_id, items=items_out,
    )


async def issue_indent(
    db: AsyncSession,
    indent_id: UUID,
    *,
    current_user_id: UUID,
    facility_id: UUID,
) -> IndentOut:
    indent_row = (
        await db.execute(
            text("""
                SELECT id, department_id, status, approved_by FROM indents
                WHERE id = :id AND facility_id = :facility_id FOR UPDATE
            """),
            {"id": str(indent_id), "facility_id": str(facility_id)},
        )
    ).mappings().first()
    if indent_row is None:
        raise HTTPException(status_code=404, detail="Indent not found")
    if indent_row["status"] != "approved":
        raise HTTPException(
            status_code=409, detail=f"Cannot issue indent in status '{indent_row['status']}'"
        )

    items = (
        await db.execute(
            text("SELECT id, item_id, quantity_requested FROM indent_items WHERE indent_id = :id"),
            {"id": str(indent_id)},
        )
    ).mappings().all()

    items_out: list[IndentItemOut] = []
    for it in items:
        remaining = it["quantity_requested"]
        batches = (
            await db.execute(
                text("""
                    SELECT ib.id, ib.quantity FROM inventory_batches ib
                    JOIN stock_locations sl ON sl.id = ib.stock_location_id
                    WHERE ib.item_id = :item_id AND sl.facility_id = :facility_id
                      AND ib.quantity > 0
                    ORDER BY ib.expiry_date ASC
                    FOR UPDATE
                """),
                {"item_id": str(it["item_id"]), "facility_id": str(facility_id)},
            )
        ).mappings().all()

        available = sum((b["quantity"] for b in batches), Decimal("0"))
        if available < remaining:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient stock for item {it['item_id']}: "
                       f"requested {remaining}, available {available}",
            )

        for batch in batches:
            if remaining <= 0:
                break
            take = min(batch["quantity"], remaining)
            ledger_id = uuid4()
            await db.execute(
                text("""
                    INSERT INTO stock_ledger
                        (id, item_id, batch_id, transaction_type, quantity,
                         reference_type, reference_id, performed_by)
                    VALUES
                        (:id, :item_id, :batch_id, 'issue', :neg_qty,
                         'indent', :indent_id, :user_id)
                """),
                {
                    "id": str(ledger_id), "item_id": str(it["item_id"]),
                    "batch_id": str(batch["id"]), "neg_qty": -take,
                    "indent_id": str(indent_id), "user_id": str(current_user_id),
                },
            )
            remaining -= take

        items_out.append(IndentItemOut(
            id=it["id"], item_id=it["item_id"], quantity_requested=it["quantity_requested"],
        ))

    await db.execute(
        text("""
            UPDATE indents SET status = 'issued', updated_by = :user_id, updated_at = now()
            WHERE id = :id
        """),
        {"user_id": str(current_user_id), "id": str(indent_id)},
    )

    await write_audit_log(
        db, facility_id=facility_id, user_id=current_user_id, action="issue",
        resource_type="indents", resource_id=indent_id,
        new_value={"item_count": len(items_out)},
    )

    return IndentOut(
        id=indent_id, department_id=indent_row["department_id"], status="issued",
        approved_by=indent_row["approved_by"], items=items_out,
    )


# -- B6-W5-01: Reorder calc -----------------------------------------------

async def get_reorder_alerts(
    db: AsyncSession,
    *,
    facility_id: UUID,
) -> ReorderAlertsResponse:
    rows = (
        await db.execute(
            text("""
                SELECT
                    ii.id AS item_id,
                    ii.name AS item_name,
                    ii.reorder_level,
                    COALESCE(SUM(ib.quantity), 0) AS current_stock
                FROM inventory_items ii
                LEFT JOIN inventory_batches ib ON ib.item_id = ii.id
                LEFT JOIN stock_locations sl
                    ON sl.id = ib.stock_location_id AND sl.facility_id = :facility_id
                WHERE ii.is_active
                GROUP BY ii.id, ii.name, ii.reorder_level
                HAVING COALESCE(SUM(ib.quantity), 0) <= ii.reorder_level
                ORDER BY ii.name
            """),
            {"facility_id": str(facility_id)},
        )
    ).mappings().all()

    return ReorderAlertsResponse(
        items=[
            ReorderAlertItem(
                item_id=r["item_id"], item_name=r["item_name"],
                reorder_level=r["reorder_level"], current_stock=r["current_stock"],
            )
            for r in rows
        ]
    )


# -- B6-W5-01: Adjustments (dual sign-off) --------------------------------

async def create_adjustment(
    db: AsyncSession,
    payload: AdjustmentCreate,
    *,
    current_user_id: UUID,
    facility_id: UUID,
) -> AdjustmentOut:
    batch_row = (
        await db.execute(
            text("""
                SELECT ib.id FROM inventory_batches ib
                JOIN stock_locations sl ON sl.id = ib.stock_location_id
                WHERE ib.id = :batch_id AND ib.item_id = :item_id AND sl.facility_id = :facility_id
            """),
            {
                "batch_id": str(payload.batch_id), "item_id": str(payload.item_id),
                "facility_id": str(facility_id),
            },
        )
    ).mappings().first()
    if batch_row is None:
        raise HTTPException(status_code=404, detail="Batch not found for this item/facility")

    if payload.first_approver_id == current_user_id:
        raise HTTPException(
            status_code=422,
            detail="The designated first approver must be different from the creator",
        )

    adjustment_id = uuid4()
    await db.execute(
        text("""
            INSERT INTO adjustments
                (id, facility_id, item_id, batch_id, quantity_change, reason,
                 first_approver_id, status, created_by, updated_by)
            VALUES
                (:id, :facility_id, :item_id, :batch_id, :quantity_change, :reason,
                 :first_approver_id, 'pending', :user_id, :user_id)
        """),
        {
            "id": str(adjustment_id), "facility_id": str(facility_id),
            "item_id": str(payload.item_id), "batch_id": str(payload.batch_id),
            "quantity_change": payload.quantity_change, "reason": payload.reason,
            "first_approver_id": str(payload.first_approver_id),
            "user_id": str(current_user_id),
        },
    )

    await write_audit_log(
        db, facility_id=facility_id, user_id=current_user_id, action="create",
        resource_type="adjustments", resource_id=adjustment_id,
        new_value={
            "item_id": str(payload.item_id), "batch_id": str(payload.batch_id),
            "quantity_change": str(payload.quantity_change), "reason": payload.reason,
        },
    )

    return AdjustmentOut(
        id=adjustment_id, item_id=payload.item_id, batch_id=payload.batch_id,
        quantity_change=payload.quantity_change, reason=payload.reason,
        first_approver_id=payload.first_approver_id, second_approver_id=None, status="pending",
    )


async def approve_adjustment(
    db: AsyncSession,
    adjustment_id: UUID,
    payload: AdjustmentApprovalRequest,
    *,
    current_user_id: UUID,
    facility_id: UUID,
) -> AdjustmentOut:
    adj_row = (
        await db.execute(
            text("""
                SELECT id, item_id, batch_id, quantity_change, reason,
                       first_approver_id, status, created_by
                FROM adjustments WHERE id = :id AND facility_id = :facility_id FOR UPDATE
            """),
            {"id": str(adjustment_id), "facility_id": str(facility_id)},
        )
    ).mappings().first()
    if adj_row is None:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    if adj_row["status"] != "pending":
        raise HTTPException(
            status_code=409, detail=f"Cannot decide adjustment in status '{adj_row['status']}'"
        )
    if current_user_id == adj_row["first_approver_id"] or current_user_id == adj_row["created_by"]:
        raise HTTPException(
            status_code=403,
            detail="The second approver must be different from both the creator and the first approver",
        )

    new_status = "approved" if payload.approve else "rejected"
    await db.execute(
        text("""
            UPDATE adjustments SET status = :status, second_approver_id = :user_id,
                updated_by = :user_id, updated_at = now()
            WHERE id = :id
        """),
        {"status": new_status, "user_id": str(current_user_id), "id": str(adjustment_id)},
    )

    if payload.approve:
        ledger_id = uuid4()
        await db.execute(
            text("""
                INSERT INTO stock_ledger
                    (id, item_id, batch_id, transaction_type, quantity,
                     reference_type, reference_id, performed_by, reason)
                VALUES
                    (:id, :item_id, :batch_id, 'adjustment', :qty,
                     'adjustments', :adjustment_id, :user_id, :reason)
            """),
            {
                "id": str(ledger_id), "item_id": str(adj_row["item_id"]),
                "batch_id": str(adj_row["batch_id"]), "qty": adj_row["quantity_change"],
                "adjustment_id": str(adjustment_id), "user_id": str(current_user_id),
                "reason": adj_row["reason"],
            },
        )

    await write_audit_log(
        db, facility_id=facility_id, user_id=current_user_id,
        action="approve" if payload.approve else "reject",
        resource_type="adjustments", resource_id=adjustment_id,
        new_value={"reason": payload.reason},
    )

    return AdjustmentOut(
        id=adjustment_id, item_id=adj_row["item_id"], batch_id=adj_row["batch_id"],
        quantity_change=adj_row["quantity_change"], reason=adj_row["reason"],
        first_approver_id=adj_row["first_approver_id"], second_approver_id=current_user_id,
        status=new_status,
    )

async def get_expiry_tracker(
    db: AsyncSession,
    *,
    facility_id: UUID,
    stock_location_id: UUID | None,
    threshold_days: int,
) -> ExpiryTrackerResponse:
    where = ["sl.facility_id = :facility_id", "ib.quantity > 0"]
    params: dict = {
        "facility_id": str(facility_id),
        "threshold_days": threshold_days,
    }
    if stock_location_id is not None:
        where.append("ib.stock_location_id = :stock_location_id")
        params["stock_location_id"] = str(stock_location_id)

    where_clause = " AND ".join(where)

    rows = (
        await db.execute(
            text(f"""
                SELECT
                    ib.id AS batch_id, ib.item_id, ii.name AS item_name,
                    ib.batch_number, ib.expiry_date, ib.quantity,
                    ib.stock_location_id, sl.name AS stock_location_name,
                    (ib.expiry_date - (now() AT TIME ZONE fac.timezone)::date) AS days_to_expiry
                FROM inventory_batches ib
                JOIN stock_locations sl ON sl.id = ib.stock_location_id
                JOIN facilities fac ON fac.id = sl.facility_id
                JOIN inventory_items ii ON ii.id = ib.item_id
                WHERE {where_clause}
                    AND (ib.expiry_date - (now() AT TIME ZONE fac.timezone)::date) <= :threshold_days
                ORDER BY ib.expiry_date ASC
            """),
            params,
        )
    ).mappings().all()

    return ExpiryTrackerResponse(
        threshold_days=threshold_days,
        items=[
            ExpiringBatch(
                batch_id=r["batch_id"], item_id=r["item_id"], item_name=r["item_name"],
                batch_number=r["batch_number"], expiry_date=r["expiry_date"].isoformat(),
                days_to_expiry=r["days_to_expiry"], quantity=r["quantity"],
                stock_location_id=r["stock_location_id"],
                stock_location_name=r["stock_location_name"],
            )
            for r in rows
        ],
    )

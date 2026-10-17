"""GET /orders/results-worklist — the doctor's outstanding results.

The screen that asks "what have I ordered, what has come back, and what still
needs my sign-off". It had no backend: the frontend fixture's own docstring
said it was "backed by GET /pathology/order-items and GET /radiology/order-items,
joined with each item's current result" — a join across two modules that no
endpoint performed and that the browser cannot do without fetching every order
item in the facility.

Why one endpoint rather than two calls plus a client-side merge:

  * The lab and radiology halves must be ranked against each other. A STAT lab
    and a routine scan sort into one list; two independently-paged calls cannot
    produce that ordering without over-fetching both.
  * The review status comes from doctor_reviews, which is keyed by
    lab_order_item_id OR radiology_order_item_id. Resolving it per row in the
    browser is N+1 over a clinician's whole worklist.

Scoping follows queue.service.get_doctor_worklist, the established precedent:
a doctor sees their own, an admin sees the facility. Both are facility-scoped
first — `orders.facility_id` is the boundary, and it is applied to both halves
of the union rather than to the result, so neither half can leak on its own.
"""
from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

# Ranking is server-side (see the ORDER BY below) and deliberately not re-sorted
# by the client. STAT before urgent before routine, then most-recently-reported
# first; items with no result yet sort last within their priority via NULLS
# LAST, because a clinician scanning this list is looking for what has come back.
_SQL = sa.text("""
WITH lab AS (
    SELECT
        li.id                      AS id,
        'lab'                      AS order_type,
        o.id                       AS order_id,
        o.order_number             AS order_number,
        o.encounter_id             AS encounter_id,
        o.patient_id               AS patient_id,
        o.priority                 AS priority,
        li.accession_number        AS accession_number,
        li.test_name               AS test_name,
        NULL                       AS modality,
        li.status                  AS status,
        r.status                   AS result_status,
        r.created_at               AS reported_at
    FROM lab_order_items li
    JOIN orders o ON o.id = li.order_id
    LEFT JOIN lab_results r
           ON r.lab_order_item_id = li.id AND r.is_current
    WHERE o.facility_id = :facility_id
      AND (:all_doctors OR o.created_by = :caller_id)
),
rad AS (
    SELECT
        ri.id                      AS id,
        'radiology'                AS order_type,
        o.id                       AS order_id,
        o.order_number             AS order_number,
        o.encounter_id             AS encounter_id,
        o.patient_id               AS patient_id,
        o.priority                 AS priority,
        ri.accession_number        AS accession_number,
        ri.scan_type               AS test_name,
        ri.modality                AS modality,
        ri.status                  AS status,
        rep.status                 AS result_status,
        rep.created_at             AS reported_at
    FROM radiology_order_items ri
    JOIN orders o ON o.id = ri.order_id
    LEFT JOIN radiology_reports rep
           ON rep.radiology_order_item_id = ri.id AND rep.is_current
    WHERE o.facility_id = :facility_id
      AND (:all_doctors OR o.created_by = :caller_id)
),
merged AS (
    SELECT * FROM lab
    UNION ALL
    SELECT * FROM rad
)
SELECT
    m.*,
    p.full_name AS patient_name,
    COALESCE(p.uhid, p.thid) AS uhid,
    dr.status AS review_status
FROM merged m
JOIN patients p ON p.id = m.patient_id
-- doctor_reviews is keyed by whichever item type the review is for, so the
-- join has to match on the correct column per row. Scoped to the caller's
-- facility as well: a review row is itself facility-stamped (0038).
-- The latest review only. A plain join listed an item once per review, so a
-- re-reviewed CBC appeared twice (QA 16 Oct 2026, duplicate React key).
LEFT JOIN LATERAL (
    SELECT d.status
      FROM doctor_reviews d
     WHERE d.facility_id = :facility_id
       AND ((m.order_type = 'lab'       AND d.lab_order_item_id = m.id)
         OR (m.order_type = 'radiology' AND d.radiology_order_item_id = m.id))
     ORDER BY d.created_at DESC
     LIMIT 1
) dr ON true
ORDER BY
    CASE m.priority WHEN 'stat' THEN 0 WHEN 'urgent' THEN 1 ELSE 2 END,
    m.reported_at DESC NULLS LAST,
    m.accession_number
LIMIT :limit
""")


async def get_results_worklist(
    db: AsyncSession,
    *,
    caller_id: uuid.UUID,
    facility_id: uuid.UUID,
    caller_roles: list[str],
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Lab and radiology order items for one clinician, ranked together.

    `all_doctors` is derived from the caller's roles, never from a query
    parameter — a doctor who could pass `all=true` would be reading colleagues'
    worklists, and the whole point of the scope is that they cannot.
    """
    all_doctors = "admin" in caller_roles

    rows = (
        await db.execute(
            _SQL,
            {
                "facility_id": str(facility_id),
                "caller_id": str(caller_id),
                "all_doctors": all_doctors,
                "limit": limit,
            },
        )
    ).mappings().all()

    return [dict(row) for row in rows]

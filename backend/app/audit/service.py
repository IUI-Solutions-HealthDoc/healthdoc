"""
Audit write-helper — the MANUAL/bulk-operation path.

Repo path: backend/app/audit/service.py

The automatic path — the actual "everyone gets this for free" mechanism
the ticket asks for — lives in app/audit/listeners.py (SQLAlchemy
before_flush/after_flush hooks that fire on every ordinary ORM mutation
with zero per-endpoint code). This file exists for the one case
listeners.py structurally can't cover: bulk SQL (session.execute(
update(...)), raw SQL, bulk_update_mappings) bypasses SQLAlchemy's
unit-of-work entirely and never populates session.new/dirty/deleted, so
listeners.py never sees it. write_audit_log() below is the fallback for
exactly that situation.

Core rule both this file and listeners.py enforce: an audit row for a
mutation must live in the SAME database transaction as the mutation
itself. That's the only way "same transaction" and "rollback on audit
failure" both hold at once, without any special-case error handling
anywhere:

  - write_audit_log() does session.add() + await session.flush(). It
    never calls session.commit(). Flush sends the INSERT to Postgres
    inside the CURRENT transaction — which is what lets the append-only
    trigger, the chain_seq-assignment trigger, and any CHECK constraint
    on audit_logs (all from migration 0003) actually run and raise
    immediately if something's wrong.
  - Nothing commits until the CALLER commits. In this repo that's
    app.common.db.get_db() — the FastAPI dependency every route already
    gets its session from. It commits exactly ONCE, after the whole
    request handler returns successfully, and rolls back if ANYTHING
    raised along the way (see its try/except). That's the entire
    mechanism — this file doesn't add separate rollback logic, it just
    makes sure the audit INSERT happens inside that same session, before
    that one commit, so Postgres's own transaction handling does the
    work for free.
  - So: if the audit insert fails after the business mutation already
    ran in the same session, the exception propagates up, the caller's
    transaction block rolls back, and BOTH the mutation and the audit
    row disappear together. Neither this file nor listeners.py
    implements rollback logic itself — nothing commits early, so
    Postgres's own transaction rollback does the work.

QUERY PATH (B7-W4-01, added below): list_audit_logs() / count_audit_logs()
/ stream_audit_logs_csv() are read-only with respect to audit_logs itself
— "read-only" in the ticket title means the business data, not this
module's own compliance obligations. The CSV export is the one exception:
per the compliance list (app/audit/actions.py: "Data export/print" is
itself an auditable event, 26.1), app/audit/router.py's export endpoint
calls write_audit_log() above to record that the export happened, same
as any other manual-path audit write — no third insert mechanism.

stream_audit_logs_csv() deliberately does NOT take the caller's request-
scoped `db` session. A FastAPI dependency declared with `yield` (get_db()
here) tears down as soon as the route handler function RETURNS — for a
StreamingResponse that happens before the generator body has produced a
single byte, so a session captured from Depends(get_db) would already be
closed by the time this generator actually runs. Same problem, same fix
as app/consent/access_log.py: open an independent SessionLocal() inside
the generator itself so its lifetime is the generator's lifetime, not the
route handler's.

Post-review update (schema doc §3 0003, v3.9+): `entry_hash`, `prev_hash`,
`signature`, and `signer_key_id` are no longer written here at all. The
inline stub that used to fake a signature on every insert made the table
LOOK tamper-evident when it wasn't — a real signature and an
"unsigned:..." placeholder were indistinguishable to a reader. All four
columns are nullable now and stay NULL until a separate, single-threaded
per-facility sealer job (not part of this file) walks unsealed rows in
`chain_seq` order and fills them in. Absence is truthful; a fake
signature was not. `_build_audit_log()` below sets none of these five
columns — that's intentional, not an oversight.
"""

import csv
import io
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import get_current_actor
from app.audit.models import AuditLog
from app.common.db import SessionLocal

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 100  # §4.3: page_size capped server-side; large exports go through /logs/export instead.


def _build_audit_log(
    *,
    facility_id: uuid.UUID,
    action: str,
    resource_type: str,
    user_id: uuid.UUID | None = None,
    role: str | None = None,
    department_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    visit_id: uuid.UUID | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
    device_id: str | None = None,
) -> AuditLog:
    """
    Builds (but does not add/flush) one AuditLog instance. Plain sync
    function on purpose — this is called both from write_audit_log()
    (async, manual path) and from listeners.py's after_flush handler
    (sync, automatic path — SQLAlchemy's flush events are not async-
    aware, no I/O happens in here regardless).

    Single source of truth for: falling back to the current request's
    actor (app/audit/context.py) when caller-supplied fields are None.
    Sets none of chain_seq/prev_hash/entry_hash/signature/
    signer_key_id/sealed_at — chain_seq is assigned by the
    trg_audit_logs_assign_chain_seq BEFORE INSERT trigger (migration
    0003), and the other five stay NULL until the async per-facility
    sealer job runs (see AuditLog's docstring in models.py). This
    function no longer signs anything — that moved out of the write
    path entirely.
    """
    actor = get_current_actor()
    if user_id is None and actor is not None:
        user_id = actor.user_id
    if role is None and actor is not None:
        role = actor.role
    if ip_address is None and actor is not None:
        ip_address = actor.ip_address
    if device_id is None and actor is not None:
        device_id = actor.device_id
    if actor is None and user_id is None:
        logger.warning(
            "_build_audit_log: no actor context and no explicit user_id "
            "(action=%s resource_type=%s) — user_id/ip_address/device_id "
            "will be NULL on this row",
            action, resource_type,
        )

    # chain_seq is trigger-assigned on INSERT; prev_hash/entry_hash/
    # signature/signer_key_id/sealed_at all stay NULL here — the async
    # per-facility sealer job fills them in later (see module docstring).
    return AuditLog(
        facility_id=facility_id,
        user_id=user_id,
        role=role,
        department_id=department_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        patient_id=patient_id,
        visit_id=visit_id,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        ip_address=ip_address,
        device_id=device_id,
    )


async def write_audit_log(
    session: AsyncSession,
    *,
    facility_id: uuid.UUID,
    action: str,
    resource_type: str,
    user_id: uuid.UUID | None = None,
    role: str | None = None,
    department_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    visit_id: uuid.UUID | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
    device_id: str | None = None,
) -> AuditLog:
    """
    MANUAL audit path — use this for bulk SQL operations (bulk_update,
    session.execute(update(...)), raw SQL) that bypass the ORM's
    unit-of-work entirely and therefore never trigger listeners.py's
    automatic before_flush/after_flush hooks (those only see
    session.new/dirty/deleted, which bulk operations don't populate).

    For ordinary ORM create/update/delete via session.add()/session.
    delete(), you do NOT need to call this — listeners.py does it
    automatically once a model opts in (see that file's docstring).

    Does NOT commit. The caller must already be inside the request's
    normal session (from app.common.db.get_db()) which also contains the
    actual mutation this call is auditing — get_db() commits once at the
    end of the request, or rolls back everything if anything raised.
    That shared session + single commit point is what makes "fails
    together, rolls back together" true, with no extra logic needed here.
    """
    entry = _build_audit_log(
        facility_id=facility_id,
        action=action,
        resource_type=resource_type,
        user_id=user_id,
        role=role,
        department_id=department_id,
        resource_id=resource_id,
        patient_id=patient_id,
        visit_id=visit_id,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        ip_address=ip_address,
        device_id=device_id,
    )
    session.add(entry)

    # Flush (NOT commit): pushes the INSERT now, inside the still-open
    # transaction, so the append-only + chain_seq-assignment triggers run and can
    # raise immediately. If they do, the exception propagates straight
    # up to the caller's transaction block, which rolls EVERYTHING back
    # -- the mutation this row was meant to record, included.
    await session.flush()

    return entry



@dataclass
class AuditCapture:
    """
    Handed to the caller's code inside `audited_mutation()` so it can
    record what changed, without needing to know AuditLog's shape.
    """

    resource_id: uuid.UUID | None = None
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    reason: str | None = None


@asynccontextmanager
async def audited_mutation(
    session: AsyncSession,
    *,
    facility_id: uuid.UUID,
    action: str,
    resource_type: str,
    user_id: uuid.UUID | None = None,
    role: str | None = None,
    department_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    visit_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    device_id: str | None = None,
):
    """
    Convenience wrapper for the common case: "do one mutation, then
    write exactly one audit row for it, in the same transaction."

    Usage (inside a service function that already has an open session):

        async with audited_mutation(
            session,
            facility_id=facility.id,
            action="update",
            resource_type="patients",
            user_id=current_user.id,
            patient_id=patient.id,
        ) as audit:
            audit.resource_id = patient.id
            audit.old_value = {"status": patient.status}
            patient.status = "merged"
            audit.new_value = {"status": patient.status}
            # no commit here -- the caller's outer transaction commits
            # the patient update and the audit row together.

    Two failure paths, both correct on purpose:

      1. The `async with` BLOCK raises (the mutation itself failed).
         write_audit_log() is never reached -- no audit row gets
         written for a mutation that never actually happened. The
         exception propagates unchanged; the caller's transaction rolls
         back the mutation on its own.

      2. write_audit_log() itself raises (e.g. a trigger rejects the
         insert) AFTER the mutation succeeded. That exception ALSO
         propagates up -- a failed audit write takes the mutation down
         with it, which is this ticket's actual requirement.
    """
    capture = AuditCapture()
    yield capture

    await write_audit_log(
        session,
        facility_id=facility_id,
        action=action,
        resource_type=resource_type,
        user_id=user_id,
        role=role,
        department_id=department_id,
        resource_id=capture.resource_id,
        patient_id=patient_id,
        visit_id=visit_id,
        old_value=capture.old_value,
        new_value=capture.new_value,
        reason=capture.reason,
        ip_address=ip_address,
        device_id=device_id,
    )


# ---------------------------------------------------------------------
# QUERY PATH — B7-W4-01: Audit query API (filters, read-only, CSV export)
# ---------------------------------------------------------------------

# CSV and the /audit/logs JSON list share this exact column set (schema
# doc §4.4) — one shape, so a reviewer diffing an exported CSV against
# the API response never has to reconcile two different field lists for
# "the same data".
CSV_COLUMNS: tuple[str, ...] = (
    "id", "user_id", "role", "action", "resource_type", "resource_id",
    "patient_id", "old_value", "new_value", "created_at", "entry_hash",
)


def _clamp_page_size(page_size: int) -> int:
    return min(max(page_size, 1), MAX_PAGE_SIZE)


def _audit_log_filters(
    *,
    facility_id: uuid.UUID,
    user_id: uuid.UUID | None,
    patient_id: uuid.UUID | None,
    resource_type: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[ColumnElement[bool]]:
    """
    Shared WHERE-clause builder for the paginated list, its count, and
    the CSV export — one place that defines what "matching rows" means,
    so the three can't silently drift apart.

    facility_id is ALWAYS applied and is never sourced from caller input
    here — app/audit/router.py resolves it server-side from CurrentDbUser,
    never a query param, per this repo's facility-scoping rule (does the
    value come from the token, or the request?).
    """
    conditions: list[ColumnElement[bool]] = [AuditLog.facility_id == facility_id]
    if user_id is not None:
        conditions.append(AuditLog.user_id == user_id)
    if patient_id is not None:
        conditions.append(AuditLog.patient_id == patient_id)
    if resource_type is not None:
        conditions.append(AuditLog.resource_type == resource_type)
    if date_from is not None:
        conditions.append(AuditLog.created_at >= date_from)
    if date_to is not None:
        conditions.append(AuditLog.created_at <= date_to)
    return conditions


async def count_audit_logs(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> int:
    conditions = _audit_log_filters(
        facility_id=facility_id, user_id=user_id, patient_id=patient_id,
        resource_type=resource_type, date_from=date_from, date_to=date_to,
    )
    q = select(func.count()).select_from(AuditLog).where(*conditions)
    return (await db.execute(q)).scalar_one()


async def list_audit_logs(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[AuditLog], int]:
    """Paginated, most-recent-first (matches the BRIN/partition ordering
    on created_at). Returns (items, total) — same shape as
    app/departments/service.py's list_departments()/list_rooms()."""
    page = max(page, 1)
    page_size = _clamp_page_size(page_size)
    conditions = _audit_log_filters(
        facility_id=facility_id, user_id=user_id, patient_id=patient_id,
        resource_type=resource_type, date_from=date_from, date_to=date_to,
    )

    total = await count_audit_logs(
        db, facility_id=facility_id, user_id=user_id, patient_id=patient_id,
        resource_type=resource_type, date_from=date_from, date_to=date_to,
    )

    q = (
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = (await db.execute(q)).scalars().all()
    return list(items), total


def _csv_row(row: AuditLog) -> list[str]:
    return [
        str(row.id),
        str(row.user_id) if row.user_id else "",
        row.role or "",
        row.action,
        row.resource_type,
        str(row.resource_id) if row.resource_id else "",
        str(row.patient_id) if row.patient_id else "",
        json.dumps(row.old_value) if row.old_value is not None else "",
        json.dumps(row.new_value) if row.new_value is not None else "",
        row.created_at.isoformat(),
        row.entry_hash or "",
    ]


async def stream_audit_logs_csv(
    *,
    facility_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> AsyncIterator[str]:
    """
    Streams matching audit_logs rows as CSV text, header first, one row
    at a time via a server-side cursor (AsyncSession.stream()) — no
    row-count cap, unlike the paginated list endpoint. Per §4.3: "large
    exports are explicit, audited endpoints" — this IS that endpoint,
    so it doesn't apply the page_size ceiling the JSON list does.

    Opens its OWN session (see module docstring for why this can't reuse
    the route handler's Depends(get_db) session) and closes it when the
    generator is exhausted or garbage-collected (the `async with` covers
    both — an early-abandoned generator still closes the session on GC/
    aclose(), so a client disconnecting mid-download doesn't leak a
    connection).
    """
    conditions = _audit_log_filters(
        facility_id=facility_id, user_id=user_id, patient_id=patient_id,
        resource_type=resource_type, date_from=date_from, date_to=date_to,
    )
    q = select(AuditLog).where(*conditions).order_by(AuditLog.created_at.desc())

    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow(CSV_COLUMNS)
    yield buf.getvalue()
    buf.seek(0)
    buf.truncate(0)

    async with SessionLocal() as session:
        result = await session.stream(q)
        async for row in result.scalars():
            writer.writerow(_csv_row(row))
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

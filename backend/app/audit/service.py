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

import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import get_current_actor
from app.audit.models import AuditLog

logger = logging.getLogger(__name__)


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

"""
Automatic audit-log writer — the real "everyone gets this for free"
mechanism this ticket asks for, instead of a helper function every
module has to remember to call individually.

Repo path: backend/app/audit/listeners.py

WHY THIS ISN'T HTTP MIDDLEWARE:
Real ASGI middleware (Starlette/FastAPI) only sees requests and
responses — it has no way to know "this Patient row's status changed
from active to merged". The layer that DOES see that is SQLAlchemy's own
session lifecycle, so this hooks into THAT instead:

  - before_flush fires right before SQLAlchemy sends any INSERT/UPDATE/
    DELETE to Postgres for the current unit of work. This is the only
    point where sqlalchemy.orm.attributes.get_history() can still show
    old-vs-new column values — that history is gone once the flush
    actually runs, so it must be captured here.
  - after_flush fires right after those statements were sent (so
    newly-INSERTed rows now have their real, DB-generated `id`), but the
    surrounding transaction is STILL OPEN — nothing has committed. This
    is where the actual AuditLog rows get built and session.add()'d.
    SQLAlchemy explicitly documents that objects added during
    after_flush are picked up and included in the SAME flush/
    transaction automatically (this is literally their own recipe for
    "write a history/audit row for every change") — no manual re-flush
    needed.

WHY THIS SATISFIES THE TICKET:
"same transaction" — the audit row is added and flushed as part of the
exact same Session's flush cycle as the business mutation, never a
separate connection or commit.
"rollback on audit failure" — if building/inserting an AuditLog row
raises (missing facility_id, a rejected trigger, whatever), the
exception propagates out of the ongoing flush, which is called from
inside app.common.db.get_db()'s try/except — that rolls back the WHOLE
session, undoing the business mutation too. No custom rollback code
anywhere; Postgres + SQLAlchemy's transaction handling does it for free.

HOW A MODULE OPTS IN — THIS IS THE "EVERYONE WILL USE THIS" PART:
Any ORM model that should be auto-audited sets class attributes on
itself. No import in the endpoint, no decorator on each route, no call
to remember — once a model declares these, every create/update/delete
against it is audited automatically for the app's whole lifetime:

    class Patient(UUIDPk, Blame, Timestamps, Base):
        __tablename__ = "patients"
        __audit_resource_type__ = "patients"      # required -- turns this on
        __audit_facility_id_field__ = "facility_id"  # required -- must exist
        __audit_patient_id_field__ = "id"          # optional, default None
        __audit_visit_id_field__ = None            # optional
        __audit_department_id_field__ = None       # optional
        ...

IMPORTANT — this file alone does not audit any other module's tables.
It only builds the mechanism. Every OTHER module's own developer has to
add those class attributes to their own models for their tables to
actually get audited — that's a rollout step across the team, not
something one file can do unilaterally. Flag this in the team channel:
"add __audit_resource_type__ + __audit_facility_id_field__ to any model
that needs audit trail, see app/audit/listeners.py for the pattern."

Audit is opt-out by default, and that's a real gap — a model in a
known-auditable module that forgets the class attributes above gets NO
audit at all, silently. `assert_audit_coverage()` below is a boot-time
check for exactly that: call it once at startup, after all models (and
this file) have been imported, and it fails fast instead of letting the
gap through quietly. See its own docstring for how modules opt in.

KNOWN LIMITATIONS (flagged, not hidden — this is a skeleton):
1. entry_hash/prev_hash/signature/signer_key_id are no longer computed
   anywhere in this file or service.py — they're sealer-computed,
   asynchronously, per facility (schema doc §3 0003). chain_seq itself
   is gapless (assigned from audit_counters, migration 0003 — see that
   migration's comments for why a raw Postgres SEQUENCE was wrong here).
   Rows written here have all five chain columns NULL until the sealer
   job runs. That job has no owner yet; Tech Lead opened it as its own
   blocking issue (#291) rather than leaving it implicit in this PR —
   the table is not tamper-evident in production until it lands.
2. Bulk operations (session.execute(update(...)), bulk_update_mappings,
   raw SQL) bypass the ORM's unit-of-work entirely and will NOT trigger
   this — they never touch session.new/dirty/deleted. Use
   service.write_audit_log() manually for those.
3. old_value/new_value capture EVERY changed column via get_history(),
   not a hand-picked summary — accurate, but potentially more verbose
   than a module actually wants for very wide tables.
4. This file must be IMPORTED SOMEWHERE AT APP STARTUP for the
   @event.listens_for(...) registrations below to actually take effect
   — merely existing on disk does nothing. Add this line to
   app/main.py (or wherever the FastAPI app is constructed):

       from app.audit import listeners  # noqa: F401  (registers audit hooks)
       listeners.assert_audit_coverage()  # fail fast on missing opt-in
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, attributes

from app.audit.actions import AuditAction
from app.audit.models import AuditLog
from app.audit.service import _build_audit_log
from app.common.db import Base

logger = logging.getLogger(__name__)

# Session.info is a plain dict that lives for the Session object's whole
# lifetime — a safe place to stash work-in-progress data between the
# before_flush and after_flush events for one flush cycle. Cleared after
# every use so nothing leaks into the next flush.
_PENDING_KEY = "_audit_pending_entries"


def _audit_config(obj: Any) -> tuple[str, str] | None:
    """
    Returns (resource_type, facility_id_field_name) if this object's
    class opted into auto-audit via __audit_resource_type__, else None
    (meaning: not our table, skip it silently).
    """
    cls = type(obj)
    resource_type = getattr(cls, "__audit_resource_type__", None)
    if resource_type is None:
        return None

    facility_field = getattr(cls, "__audit_facility_id_field__", None)
    if facility_field is None:
        logger.error(
            "%s sets __audit_resource_type__='%s' but not "
            "__audit_facility_id_field__ — skipping auto-audit for this "
            "object. audit_logs.facility_id is NOT NULL; every auditable "
            "model must declare which of its own columns supplies it.",
            cls.__name__, resource_type,
        )
        return None
    return resource_type, facility_field


def _resolve_related_id(obj: Any, attr_name: str | None) -> UUID | None:
    if not attr_name:
        return None
    return getattr(obj, attr_name, None)


def _json_safe(value: Any) -> Any:
    """
    Convert a raw Python attribute value into something SQLAlchemy's
    JSON serializer can actually write to a JSONB column.

    get_history() hands back real Python objects -- uuid.UUID,
    datetime/date, Decimal -- not JSON primitives. The stdlib json
    encoder (what SQLAlchemy's JSON type uses by default) has no idea
    how to serialize those and raises TypeError. Since schema-
    conventions.md rule #2 makes UUID the primary key of every table in
    this app, this bit ANY auditable model's first insert -- caught by
    test_opted_in_model_create_produces_exactly_one_audit_row, not
    found in review, because nobody had wired a real model into
    listeners.py yet to notice.
    """
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _column_snapshot(obj: Any, *, want_old: bool) -> dict[str, Any]:
    """
    A {column_name: value} dict for every mapped column that actually
    changed on this object, using SQLAlchemy's own attribute history.
    want_old=True -> values BEFORE the change (for old_value).
    want_old=False -> values AFTER the change (for new_value).
    Values are passed through _json_safe() so old_value/new_value can
    actually be written to their JSONB columns.
    """
    mapper = inspect(type(obj))
    snapshot: dict[str, Any] = {}
    for column_attr in mapper.column_attrs:
        history = attributes.get_history(obj, column_attr.key)
        if want_old:
            if history.deleted:
                snapshot[column_attr.key] = _json_safe(history.deleted[0])
        else:
            if history.added:
                snapshot[column_attr.key] = _json_safe(history.added[0])
    return snapshot


@event.listens_for(Session, "before_flush")
def _capture_audit_diffs(session: Session, flush_context, instances) -> None:
    """
    Runs BEFORE SQLAlchemy sends INSERT/UPDATE/DELETE for this flush.
    Captures everything we CAN capture now (old/new values; resource_id
    and related-FK ids for update/delete, since those objects already
    have stable values). For newly-created rows, resource_id and any
    related id that happens to equal the object's own (not-yet-assigned)
    `id` are deferred to after_flush — server-generated UUID primary
    keys genuinely don't exist yet at this point.
    """
    pending: list[dict[str, Any]] = session.info.setdefault(_PENDING_KEY, [])

    for obj in session.new:
        config = _audit_config(obj)
        if config is None:
            continue
        resource_type, facility_field = config
        cls = type(obj)
        pending.append(
            {
                "phase": AuditAction.CREATE,
                "obj": obj,  # kept ONLY to re-read obj.id etc. after insert
                "resource_type": resource_type,
                "facility_field": facility_field,
                "patient_field": getattr(cls, "__audit_patient_id_field__", None),
                "visit_field": getattr(cls, "__audit_visit_id_field__", None),
                "department_field": getattr(cls, "__audit_department_id_field__", None),
                "old_value": None,
                "new_value": _column_snapshot(obj, want_old=False),
            }
        )

    for obj in session.dirty:
        if not session.is_modified(obj, include_collections=False):
            continue
        config = _audit_config(obj)
        if config is None:
            continue
        resource_type, facility_field = config
        cls = type(obj)
        patient_field = getattr(cls, "__audit_patient_id_field__", None)
        visit_field = getattr(cls, "__audit_visit_id_field__", None)
        department_field = getattr(cls, "__audit_department_id_field__", None)
        pending.append(
            {
                "phase": AuditAction.UPDATE,
                "resource_type": resource_type,
                "resource_id": getattr(obj, "id", None),
                "facility_id": getattr(obj, facility_field, None),
                "patient_id": _resolve_related_id(obj, patient_field),
                "visit_id": _resolve_related_id(obj, visit_field),
                "department_id": _resolve_related_id(obj, department_field),
                "old_value": _column_snapshot(obj, want_old=True),
                "new_value": _column_snapshot(obj, want_old=False),
            }
        )

    for obj in session.deleted:
        config = _audit_config(obj)
        if config is None:
            continue
        resource_type, facility_field = config
        cls = type(obj)
        patient_field = getattr(cls, "__audit_patient_id_field__", None)
        visit_field = getattr(cls, "__audit_visit_id_field__", None)
        department_field = getattr(cls, "__audit_department_id_field__", None)
        pending.append(
            {
                "phase": AuditAction.DELETE,
                "resource_type": resource_type,
                # Captured NOW, not in after_flush -- accessing a
                # deleted instance's attributes post-flush can raise
                # ObjectDeletedError if SQLAlchemy tries to refresh it.
                "resource_id": getattr(obj, "id", None),
                "facility_id": getattr(obj, facility_field, None),
                "patient_id": _resolve_related_id(obj, patient_field),
                "visit_id": _resolve_related_id(obj, visit_field),
                "department_id": _resolve_related_id(obj, department_field),
                "old_value": _column_snapshot(obj, want_old=True),
                "new_value": None,
            }
        )


@event.listens_for(Session, "after_flush")
def _write_captured_audit_entries(session: Session, flush_context) -> None:
    """
    Runs AFTER the main INSERT/UPDATE/DELETE statements executed, so
    newly-created rows now have their real DB-generated `id`. Finalizes
    each pending entry (resolving resource_id/related ids for the
    "create" phase, which couldn't be known before) and adds the actual
    AuditLog row to the session — SQLAlchemy folds this into the same
    ongoing flush/transaction automatically.
    """
    pending = session.info.pop(_PENDING_KEY, [])
    if not pending:
        return

    for entry in pending:
        if entry["phase"] == AuditAction.CREATE:
            obj = entry.pop("obj")
            entry["resource_id"] = getattr(obj, "id", None)
            entry["facility_id"] = getattr(obj, entry["facility_field"], None)
            entry["patient_id"] = _resolve_related_id(obj, entry["patient_field"])
            entry["visit_id"] = _resolve_related_id(obj, entry["visit_field"])
            entry["department_id"] = _resolve_related_id(obj, entry["department_field"])

        facility_id = entry["facility_id"]
        if facility_id is None:
            # audit_logs.facility_id is NOT NULL. Raising here fails
            # the flush, which correctly takes the mutation down with
            # it, rather than silently writing a broken audit row or
            # silently skipping audit for a real mutation.
            raise ValueError(
                f"{entry['resource_type']}: cannot write audit_logs row, "
                f"resolved facility_id is None (phase={entry['phase']})"
            )

        audit_log: AuditLog = _build_audit_log(
            facility_id=facility_id,
            action=entry["phase"],
            resource_type=entry["resource_type"],
            resource_id=entry.get("resource_id"),
            patient_id=entry.get("patient_id"),
            visit_id=entry.get("visit_id"),
            department_id=entry.get("department_id"),
            old_value=entry["old_value"],
            new_value=entry["new_value"],
        )
        session.add(audit_log)


# Module import paths (dotted prefixes of __module__) that are expected to
# declare __audit_resource_type__ on every mapped model. This is a plain
# allowlist, not a scan of the whole app, because plenty of real models
# (lookup/reference tables, event logs already append-only by construction,
# etc.) legitimately opt out — a blanket "every model must audit" check
# would be wrong, not just noisy.
#
# Rollout owner: Vaani Choudhary (B7) — tracked in issue #290
# (audit-opt-in-rollout). Target: every core-clinical/financial module
# (patients, visits, orders, billing, consent, files) added here by end
# of Sprint W2, one PR per module alongside that module's own
# __audit_resource_type__ additions. This list starts empty on purpose:
# an empty/incomplete list means assert_audit_coverage() can't catch a
# gap it doesn't know to look for, so growing it module-by-module IS the
# rollout — not a one-time task, and not blocking on this PR.
AUDITABLE_MODULE_PREFIXES: tuple[str, ...] = (
    # "app.patients",
    # "app.billing",
)


def assert_audit_coverage() -> None:
    """
    Boot-time check for the "opt-out by default" gap flagged in review:
    a model in a known-auditable module that forgets
    __audit_resource_type__ gets no audit trail at all, silently. Call
    this once at startup, after every model module has been imported
    (so Base.registry.mappers is fully populated) — see this file's
    top-of-module docstring for where.

    Raises RuntimeError (fail the boot) rather than logging, on purpose:
    a missing audit hook on a compliance-relevant table is a "must fix
    before this process serves traffic" issue, not a warning someone
    might not read.
    """
    missing: list[str] = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        module = getattr(cls, "__module__", "")
        if not any(module.startswith(prefix) for prefix in AUDITABLE_MODULE_PREFIXES):
            continue
        if getattr(cls, "__audit_resource_type__", None) is None:
            missing.append(f"{module}.{cls.__name__}")

    if missing:
        raise RuntimeError(
            "assert_audit_coverage: the following models live in a "
            "known-auditable module but don't declare "
            "__audit_resource_type__ (see app/audit/listeners.py for the "
            "pattern): " + ", ".join(sorted(missing))
        )

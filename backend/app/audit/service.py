"""Audit log writer.

Computes the same append-only hash chain that migrations/versions/
0003_audit.py's trg_audit_logs_compute_hash trigger computes in
production, plus an Ed25519 signature over the row's semantic content
(schema doc §3-0003 / architecture doc §27.6).

In production Postgres, the BEFORE INSERT trigger unconditionally
recomputes and overwrites prev_hash/entry_hash from live DB state after
this INSERT runs — so those two values are only authoritative here in
environments without the trigger (i.e. the test DB, which uses
Base.metadata.create_all and never runs Alembic migrations).

Known limitation (same one flagged in the migration's own comments):
the prev_hash lookup below is a plain SELECT with no row locking, so
concurrent writers could race and pick the same prev_hash. Acceptable
at pilot/dev volume; not solved here.
"""
import json
import uuid
from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.audit.signing import get_signer_key_id, sign


def _concat_ws(sep: str, *parts) -> str:
    """Mirrors Postgres concat_ws: skips args that are None entirely."""
    return sep.join(str(p) for p in parts if p is not None)


async def _get_prev_hash(db: AsyncSession) -> str:
    stmt = select(AuditLog.entry_hash).order_by(
        AuditLog.created_at.desc(), AuditLog.id.desc()
    ).limit(1)
    result = await db.execute(stmt)
    last_hash = result.scalar_one_or_none()
    return last_hash or ("0" * 64)


async def write_audit_log(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    user_id: uuid.UUID | None,
    role: str | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    visit_id: uuid.UUID | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
    reason: str | None = None,
    department_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    device_id: str | None = None,
) -> AuditLog:
    entry_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)

    prev_hash = await _get_prev_hash(db)

    old_value_text = json.dumps(old_value) if old_value is not None else ""
    new_value_text = json.dumps(new_value) if new_value is not None else ""
    hash_payload = _concat_ws(
        "|",
        entry_id, created_at.isoformat(), facility_id, user_id,
        action, resource_type, resource_id, patient_id, visit_id,
        old_value_text, new_value_text,
    )
    entry_hash = sha256((prev_hash + hash_payload).encode("utf-8")).hexdigest()

    sig_payload = {
        "id": str(entry_id),
        "created_at": created_at.isoformat(),
        "facility_id": str(facility_id),
        "user_id": str(user_id) if user_id else None,
        "role": role,
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id else None,
        "patient_id": str(patient_id) if patient_id else None,
        "visit_id": str(visit_id) if visit_id else None,
        "old_value": old_value,
        "new_value": new_value,
        "reason": reason,
    }
    sig_bytes = json.dumps(sig_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = sign(sig_bytes)

    entry = AuditLog(
        id=entry_id,
        created_at=created_at,
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
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        signature=signature,
        signer_key_id=get_signer_key_id(),
    )
    db.add(entry)
    await db.flush()
    return entry

"""
Service functions for the consent module.

Repo path: backend/app/consent/service.py

list_consent_records_for_patient predates this ticket (backs the
/patients/{patient_id}/records route). Everything else is B7-W4-02:
Consent CRUD — purpose/scope/channel, nullable expiry, status
transitions.

AUDIT: consent_records has no facility_id column of its own (see
models.py) so listeners.py's automatic __audit_resource_type__ opt-in
structurally cannot apply here — every mutation below goes through
app.audit.service.audited_mutation() manually, same pattern
app/billing/service.py already uses for its own facility-id-less
tables. facility_id for the audit row is the ACTING USER's own
facility (resolved in router.py from CurrentDbUser), not the patient's
— patients isn't a real table yet (0006 unmerged), so there's no
patient-facility to read regardless.

STATUS TRANSITIONS ARE ENFORCED HERE, NOT BY THE DATABASE:
trg_consent_records_freeze (migration 0004) allows any UPDATE to
`status`, it doesn't know which transitions are legal. Two paths exist
on purpose, and each can only produce its own outcomes:
  - requested -> granted/denied: transition_consent_status() below, a
    direct UPDATE.
  - granted -> revoked (or -> expired for a system sweep):
    UNREACHABLE from transition_consent_status() — only
    withdraw_consent() (a consent_withdrawals INSERT) can produce
    those, because trg_consent_withdrawals_flip_status is the only
    thing allowed to set them, and it already guards against a
    terminal-status double-withdrawal via FOR UPDATE.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.audit.service import audited_mutation
from app.common.enums import ConsentStatus
from app.consent.models import ConsentPurpose, ConsentRecord, ConsentWithdrawal

# requested -> {granted, denied} only. granted has no entry here at all
# — see module docstring for why that transition can only happen
# through withdraw_consent(), never this map.
_LEGAL_DIRECT_TRANSITIONS: dict[str, set[str]] = {
    ConsentStatus.REQUESTED.value: {ConsentStatus.GRANTED.value, ConsentStatus.DENIED.value},
}


async def list_consent_records_for_patient(
    db: AsyncSession, patient_id: uuid.UUID
) -> list[ConsentRecord]:
    result = await db.execute(
        sa.select(ConsentRecord)
        .where(ConsentRecord.patient_id == patient_id)
        .order_by(ConsentRecord.granted_at.desc())
    )
    return list(result.scalars().all())


async def list_consent_purposes(
    db: AsyncSession, *, is_active: bool | None = True
) -> list[ConsentPurpose]:
    q = sa.select(ConsentPurpose).order_by(ConsentPurpose.purpose_code)
    if is_active is not None:
        q = q.where(ConsentPurpose.is_active == is_active)
    return list((await db.execute(q)).scalars().all())


async def get_consent_record(db: AsyncSession, consent_id: uuid.UUID) -> ConsentRecord:
    record = await db.get(ConsentRecord, consent_id)
    if record is None:
        raise HTTPException(404, "Consent record not found")
    return record


async def create_consent_record(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    facility_id: uuid.UUID,
    created_by: uuid.UUID,
    purpose_id: uuid.UUID,
    granted_by_type: str,
    channel: str,
    status: str = ConsentStatus.GRANTED.value,
    visit_id: uuid.UUID | None = None,
    granted_by_user_id: uuid.UUID | None = None,
    guardian_name: str | None = None,
    guardian_relationship: str | None = None,
    expires_at: datetime | None = None,
    scope: list[str] | None = None,
    consent_artefact_id: str | None = None,
    consent_artefact_signature: str | None = None,
) -> ConsentRecord:
    purpose = await db.get(ConsentPurpose, purpose_id)
    if purpose is None:
        raise HTTPException(404, "Consent purpose not found")

    async with audited_mutation(
        db,
        facility_id=facility_id,
        action=AuditAction.CREATE,
        resource_type="consent_records",
        patient_id=patient_id,
        visit_id=visit_id,
    ) as audit:
        record = ConsentRecord(
            id=uuid.uuid4(),
            patient_id=patient_id,
            visit_id=visit_id,
            purpose_id=purpose_id,
            granted_by_type=granted_by_type,
            granted_by_user_id=granted_by_user_id,
            guardian_name=guardian_name,
            guardian_relationship=guardian_relationship,
            expires_at=expires_at,
            scope=scope,
            channel=channel,
            consent_artefact_id=consent_artefact_id,
            consent_artefact_signature=consent_artefact_signature,
            status=status,
            created_by=created_by,
        )
        db.add(record)
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(422, f"Could not create consent record: {exc.orig}") from exc
        await db.refresh(record)

        audit.resource_id = record.id
        audit.new_value = {"purpose_id": str(purpose_id), "channel": channel, "status": status}

    return record


async def transition_consent_status(
    db: AsyncSession,
    consent_id: uuid.UUID,
    *,
    new_status: str,
    reason: str | None,
    facility_id: uuid.UUID,
    updated_by: uuid.UUID,
) -> ConsentRecord:
    record = await get_consent_record(db, consent_id)
    allowed = _LEGAL_DIRECT_TRANSITIONS.get(record.status, set())
    if new_status not in allowed:
        hint = (
            " -- withdraw the consent instead" if record.status == ConsentStatus.GRANTED.value else ""
        )
        raise HTTPException(
            409,
            f"Cannot transition consent {consent_id} from '{record.status}' to "
            f"'{new_status}' directly{hint}",
        )

    async with audited_mutation(
        db,
        facility_id=facility_id,
        action=AuditAction.UPDATE,
        resource_type="consent_records",
        patient_id=record.patient_id,
        visit_id=record.visit_id,
    ) as audit:
        audit.resource_id = record.id
        audit.old_value = {"status": record.status}

        record.status = new_status
        record.status_changed_at = datetime.now(timezone.utc)
        record.updated_by = updated_by

        audit.new_value = {"status": new_status}
        audit.reason = reason
        await db.flush()

    return record


async def withdraw_consent(
    db: AsyncSession,
    consent_id: uuid.UUID,
    *,
    withdrawn_by_type: str,
    withdrawn_by_user_id: uuid.UUID | None,
    reason: str | None,
    facility_id: uuid.UUID,
) -> ConsentWithdrawal:
    record = await get_consent_record(db, consent_id)  # 404s if missing

    async with audited_mutation(
        db,
        facility_id=facility_id,
        action=AuditAction.UPDATE,
        resource_type="consent_withdrawals",
        patient_id=record.patient_id,
        visit_id=record.visit_id,
    ) as audit:
        withdrawal = ConsentWithdrawal(
            id=uuid.uuid4(),
            consent_id=consent_id,
            withdrawn_by_type=withdrawn_by_type,
            withdrawn_by_user_id=withdrawn_by_user_id,
            reason=reason,
        )
        db.add(withdrawal)
        try:
            # trg_consent_withdrawals_flip_status runs as part of this
            # INSERT and raises (DBAPIError) if `record`'s status is
            # already terminal (revoked/denied/expired) -- migration
            # 0004. Translate that into a clean 409 instead of a 500.
            await db.flush()
        except DBAPIError as exc:
            await db.rollback()
            raise HTTPException(409, f"Cannot withdraw consent {consent_id}: {exc.orig}") from exc
        await db.refresh(withdrawal)

        audit.resource_id = withdrawal.id
        audit.new_value = {"withdrawn_by_type": withdrawn_by_type}
        audit.reason = reason

    return withdrawal

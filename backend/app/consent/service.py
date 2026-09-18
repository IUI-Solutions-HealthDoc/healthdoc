"""
Service functions for the consent module.

Repo path: backend/app/consent/service.py

B7-W4-02: Consent CRUD — purpose/scope/channel, nullable expiry,
status transitions.

consent_records has no facility_id column, so mutations audit
manually via audited_mutation() rather than listeners.py's automatic
path. get_consent_record() joins to patients.facility_id (no FK
required for a join) when facility_id is passed.

trg_consent_records_freeze (migration 0004) allows any UPDATE to
`status` but doesn't validate the transition. requested->granted/denied
goes through transition_consent_status() (direct UPDATE);
granted->revoked/expired only via withdraw_consent() (consent_withdrawals
insert, trigger-flipped, FOR UPDATE guarded against double-withdrawal).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.audit.service import audited_mutation
from app.common.enums import ConsentChannel, ConsentStatus
from app.consent.models import (
    BreakGlassGrant,
    ConsentPurpose,
    ConsentRecord,
    ConsentRenewalReminder,
    ConsentWithdrawal,
)
from app.dpdp.models import ConsentManager
from app.patients.models import Patient

# requested -> {granted, denied} only. granted has no entry here at all
# — see module docstring for why that transition can only happen
# through withdraw_consent(), never this map.
_LEGAL_DIRECT_TRANSITIONS: dict[str, set[str]] = {
    ConsentStatus.REQUESTED.value: {ConsentStatus.GRANTED.value, ConsentStatus.DENIED.value},
}

# Not specified anywhere in the schema doc -- best guess, confirm before
# merge. Only used when a withdrawn consent actually had a scope to act on.
CASCADE_DEADLINE_HOURS = 72


def _build_cascade_plan(scope: list[str] | None) -> dict[str, str] | None:
    """cascaded_actions logs INTENT (what needs downstream cleanup and
    by when), not execution -- same "job, not a column" split as
    consent expiry. No mark-complete workflow here on purpose; that's
    a scheduled job's job, not this ticket's."""
    if not scope:
        return None
    return {s: "pending" for s in scope}


async def list_consent_records_for_patient(
    db: AsyncSession, patient_id: uuid.UUID, *, facility_id: uuid.UUID | None = None
) -> list[ConsentRecord]:
    q = (
        sa.select(ConsentRecord, ConsentPurpose.purpose_code, ConsentPurpose.description)
        .outerjoin(ConsentPurpose, ConsentPurpose.id == ConsentRecord.purpose_id)
        .where(ConsentRecord.patient_id == patient_id)
    )
    if facility_id is not None:
        q = q.join(Patient, Patient.id == ConsentRecord.patient_id).where(
            Patient.facility_id == facility_id
        )
    q = q.order_by(ConsentRecord.granted_at.desc())
    result = await db.execute(q)
    rows: list[ConsentRecord] = []
    for record, p_code, p_desc in result.all():
        record.purpose_code = p_code
        record.purpose_label = p_desc or (p_code.replace("_", " ").title() if p_code else None)
        rows.append(record)
    return rows


async def list_consent_purposes(
    db: AsyncSession, *, is_active: bool | None = True
) -> list[ConsentPurpose]:
    q = sa.select(ConsentPurpose).order_by(ConsentPurpose.purpose_code)
    if is_active is not None:
        q = q.where(ConsentPurpose.is_active == is_active)
    return list((await db.execute(q)).scalars().all())


async def find_active_consent(
    db: AsyncSession, *, patient_id: uuid.UUID, purpose_code: str
) -> ConsentRecord | None:
    """Most recent granted, non-expired consent for (patient_id,
    purpose_code) -- used by access_log.py to populate
    data_access_log.consent_id/consent_verified on every logged read."""
    q = (
        sa.select(ConsentRecord)
        .join(ConsentPurpose, ConsentPurpose.id == ConsentRecord.purpose_id)
        .where(
            ConsentRecord.patient_id == patient_id,
            ConsentPurpose.purpose_code == purpose_code,
            ConsentRecord.status == ConsentStatus.GRANTED.value,
            sa.or_(ConsentRecord.expires_at.is_(None), ConsentRecord.expires_at > sa.func.now()),
        )
        .order_by(ConsentRecord.granted_at.desc())
        .limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none()


async def find_active_break_glass_grant(
    db: AsyncSession, *, patient_id: uuid.UUID, user_id: uuid.UUID
) -> BreakGlassGrant | None:
    """The caller's current emergency grant for one patient, if any."""
    q = (
        sa.select(BreakGlassGrant)
        .where(
            BreakGlassGrant.patient_id == patient_id,
            BreakGlassGrant.granted_to_user_id == user_id,
            BreakGlassGrant.expires_at > sa.func.now(),
            BreakGlassGrant.revoked_at.is_(None),
        )
        .order_by(BreakGlassGrant.expires_at.desc())
        .limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none()


@dataclass(frozen=True)
class ClinicalAccessDecision:
    """Server-owned answer for a consent-gated clinical read."""

    allowed: bool
    consent: ConsentRecord | None = None
    grant: BreakGlassGrant | None = None
    blocked_reason: str | None = None


async def evaluate_clinical_access(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    user_id: uuid.UUID,
    purpose_code: str = "clinical_review",
) -> ClinicalAccessDecision:
    """Allow an active consent or the caller's active break-glass grant.

    The browser must never decide this from fixtures or a timer. Both consent
    and emergency expiry are evaluated against PostgreSQL time on each read.
    """
    consent = await find_active_consent(
        db, patient_id=patient_id, purpose_code=purpose_code
    )
    if consent is not None:
        return ClinicalAccessDecision(allowed=True, consent=consent)

    grant = await find_active_break_glass_grant(
        db, patient_id=patient_id, user_id=user_id
    )
    if grant is not None:
        return ClinicalAccessDecision(allowed=True, grant=grant)

    latest = (
        await db.execute(
            sa.select(ConsentRecord)
            .join(ConsentPurpose, ConsentPurpose.id == ConsentRecord.purpose_id)
            .where(
                ConsentRecord.patient_id == patient_id,
                ConsentPurpose.purpose_code == purpose_code,
            )
            .order_by(ConsentRecord.status_changed_at.desc(), ConsentRecord.granted_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest is None:
        reason = "consent_absent"
    elif latest.status == ConsentStatus.REVOKED.value:
        reason = "consent_revoked"
    elif (
        latest.status == ConsentStatus.EXPIRED.value
        or latest.expires_at is not None
        and latest.expires_at <= datetime.now(UTC)
    ):
        reason = "consent_expired"
    else:
        # requested/denied grants are not permission to expose the record.
        reason = "consent_absent"

    return ClinicalAccessDecision(allowed=False, blocked_reason=reason)


async def get_consent_record(
    db: AsyncSession, consent_id: uuid.UUID, *, facility_id: uuid.UUID | None = None
) -> ConsentRecord:
    q = (
        sa.select(ConsentRecord, ConsentPurpose.purpose_code, ConsentPurpose.description)
        .outerjoin(ConsentPurpose, ConsentPurpose.id == ConsentRecord.purpose_id)
        .where(ConsentRecord.id == consent_id)
    )
    if facility_id is not None:
        q = q.join(Patient, Patient.id == ConsentRecord.patient_id).where(
            Patient.facility_id == facility_id
        )
    row = (await db.execute(q)).first()
    if row is None:
        raise HTTPException(404, "Consent record not found")
    record, p_code, p_desc = row
    record.purpose_code = p_code
    record.purpose_label = p_desc or (p_code.replace("_", " ").title() if p_code else None)
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
    consent_manager_id: uuid.UUID | None = None,
) -> ConsentRecord:
    purpose = await db.get(ConsentPurpose, purpose_id)
    if purpose is None:
        raise HTTPException(404, "Consent purpose not found")
    is_abdm_manager_channel = channel == ConsentChannel.ABDM_CONSENT_MANAGER.value
    if is_abdm_manager_channel and consent_manager_id is None:
        raise HTTPException(
            422,
            detail={
                "code": "consent_manager_required",
                "message": "ABDM consent-manager records require consent_manager_id",
            },
        )
    if not is_abdm_manager_channel and consent_manager_id is not None:
        raise HTTPException(
            422,
            detail={
                "code": "consent_manager_channel_mismatch",
                "message": "consent_manager_id requires channel=abdm_consent_manager",
            },
        )
    if consent_manager_id is not None:
        manager = await db.get(ConsentManager, consent_manager_id)
        if manager is None:
            raise HTTPException(404, "Consent manager not found")
        if not manager.is_active:
            raise HTTPException(
                409,
                detail={"code": "consent_manager_inactive"},
            )

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
            consent_manager_id=consent_manager_id,
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
        audit.new_value = {
            "purpose_id": str(purpose_id),
            "channel": channel,
            "status": status,
            "consent_manager_id": str(consent_manager_id)
            if consent_manager_id
            else None,
        }

    purpose = await db.get(ConsentPurpose, purpose_id)
    if purpose is not None:
        record.purpose_code = purpose.purpose_code
        record.purpose_label = purpose.description or purpose.purpose_code.replace("_", " ").title()

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
    record = await get_consent_record(db, consent_id, facility_id=facility_id)
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
        record.status_changed_at = datetime.now(UTC)
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
    # Note: the trigger-driven status flip below doesn't bump updated_at
    # (raw SQL, not ORM) — inconsistent with transition_consent_status()'s
    # ORM-path update. Fix belongs in migration 0004's trigger SQL.
    record = await get_consent_record(db, consent_id, facility_id=facility_id)  # 404s if missing

    async with audited_mutation(
        db,
        facility_id=facility_id,
        action=AuditAction.UPDATE,
        resource_type="consent_withdrawals",
        patient_id=record.patient_id,
        visit_id=record.visit_id,
    ) as audit:
        withdrawn_at = datetime.now(UTC)
        cascaded_actions = _build_cascade_plan(record.scope)
        withdrawal = ConsentWithdrawal(
            id=uuid.uuid4(),
            consent_id=consent_id,
            withdrawn_by_type=withdrawn_by_type,
            withdrawn_by_user_id=withdrawn_by_user_id,
            withdrawn_at=withdrawn_at,
            reason=reason,
            cascaded_actions=cascaded_actions,
            cascade_deadline=(
                withdrawn_at + timedelta(hours=CASCADE_DEADLINE_HOURS) if cascaded_actions else None
            ),
        )
        db.add(withdrawal)
        try:
            # Match the trigger's specific message -- a bare except
            # would also catch an unrelated error (e.g. FK violation)
            # and mislabel it as "already withdrawn".
            await db.flush()
        except DBAPIError as exc:
            if "terminal status" not in str(exc.orig):
                raise
            await db.rollback()
            raise HTTPException(409, f"Cannot withdraw consent {consent_id}: {exc.orig}") from exc
        await db.refresh(withdrawal)

        # Cascade: an unsent "renew your consent" reminder for a consent
        # that's now revoked is exactly the kind of thing that undermines
        # a DPDP-compliance story. Same transaction as the withdrawal.
        await db.execute(
            sa.delete(ConsentRenewalReminder).where(
                ConsentRenewalReminder.consent_id == consent_id,
                ConsentRenewalReminder.sent_at.is_(None),
            )
        )

        audit.resource_id = withdrawal.id
        audit.new_value = {"withdrawn_by_type": withdrawn_by_type, "cascaded_actions": cascaded_actions}
        audit.reason = reason

    return withdrawal

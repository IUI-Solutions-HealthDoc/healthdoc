"""
Tests for the consent CRUD service layer (B7-W4-02).

Repo path: backend/tests/consent/test_crud_api.py

Service-level, real Postgres — same convention as test_0004_consent.py
in this package, and as tests/audit/test_query_api.py: the behavior
under test (trg_consent_records_freeze, trg_consent_withdrawals_flip_status,
this ticket's own transition-legality guard) is either a real Postgres
trigger or logic that calls straight through to one, so router.py stays
thin wiring and the actual behavior is verified here.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.consent import service

pytestmark = pytest.mark.asyncio


@pytest.fixture
def session_factory(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _audit_row_for(engine: AsyncEngine, *, resource_type: str, resource_id: uuid.UUID):
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT action, resource_type, old_value, new_value, reason FROM audit_logs "
                "WHERE resource_type = :rt AND resource_id = :rid "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"rt": resource_type, "rid": resource_id},
        )
        return result.one_or_none()


class TestCreateConsentRecord:
    async def test_creates_a_record_and_writes_an_audit_row(
        self, session_factory, engine: AsyncEngine, facility_id, user_id, purpose_id
    ):
        """The ticket's own acceptance criterion: audit log written on
        mutations. consent_records has no facility_id column, so this is
        the one place that proves audited_mutation() actually ran rather
        than being silently skipped like listeners.py would for a table
        missing __audit_facility_id_field__."""
        patient_id = uuid.uuid4()
        async with session_factory() as db:
            record = await service.create_consent_record(
                db,
                patient_id=patient_id,
                facility_id=facility_id,
                created_by=user_id,
                purpose_id=purpose_id,
                granted_by_type="patient",
                channel="verbal",
            )
            await db.commit()

        assert record.status == "granted"  # default
        assert record.patient_id == patient_id

        audit_row = await _audit_row_for(engine, resource_type="consent_records", resource_id=record.id)
        assert audit_row is not None
        assert audit_row.action == "create"
        assert audit_row.new_value["status"] == "granted"

    async def test_nonexistent_purpose_id_raises_404(
        self, session_factory, facility_id, user_id
    ):
        async with session_factory() as db:
            with pytest.raises(HTTPException) as exc_info:
                await service.create_consent_record(
                    db,
                    patient_id=uuid.uuid4(),
                    facility_id=facility_id,
                    created_by=user_id,
                    purpose_id=uuid.uuid4(),  # doesn't exist
                    granted_by_type="patient",
                    channel="verbal",
                )
        assert exc_info.value.status_code == 404

    async def test_nullable_expires_at_and_scope_round_trip(
        self, session_factory, facility_id, user_id, purpose_id
    ):
        """Proves the two fields the ticket title calls out by name:
        nullable expiry (None is accepted, not coerced to a default) and
        scope (a real list survives the round trip)."""
        async with session_factory() as db:
            record = await service.create_consent_record(
                db,
                patient_id=uuid.uuid4(),
                facility_id=facility_id,
                created_by=user_id,
                purpose_id=purpose_id,
                granted_by_type="guardian",
                channel="written",
                expires_at=None,
                scope=["lab_results", "prescriptions"],
            )
            await db.commit()

        assert record.expires_at is None
        assert record.scope == ["lab_results", "prescriptions"]


class TestTransitionConsentStatus:
    async def test_requested_to_granted_succeeds(
        self, session_factory, engine: AsyncEngine, facility_id, user_id, purpose_id
    ):
        async with session_factory() as db:
            record = await service.create_consent_record(
                db,
                patient_id=uuid.uuid4(),
                facility_id=facility_id,
                created_by=user_id,
                purpose_id=purpose_id,
                granted_by_type="patient",
                channel="abdm_consent_manager",
                status="requested",
            )
            await db.commit()
            consent_id = record.id

        async with session_factory() as db:
            updated = await service.transition_consent_status(
                db, consent_id, new_status="granted", reason="patient approved in app",
                facility_id=facility_id, updated_by=user_id,
            )
            await db.commit()

        assert updated.status == "granted"
        assert updated.updated_by == user_id

        audit_row = await _audit_row_for(engine, resource_type="consent_records", resource_id=consent_id)
        assert audit_row.action == "update"
        assert audit_row.reason == "patient approved in app"

    async def test_granted_to_revoked_directly_is_rejected(
        self, session_factory, facility_id, user_id, purpose_id
    ):
        """The transition this endpoint must NEVER be able to perform —
        see service.py's module docstring. Only withdraw_consent() may
        produce this outcome."""
        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=uuid.uuid4(), facility_id=facility_id, created_by=user_id,
                purpose_id=purpose_id, granted_by_type="patient", channel="verbal",
            )
            await db.commit()
            consent_id = record.id

        async with session_factory() as db:
            with pytest.raises(HTTPException) as exc_info:
                await service.transition_consent_status(
                    db, consent_id, new_status="revoked", reason=None,
                    facility_id=facility_id, updated_by=user_id,
                )
        assert exc_info.value.status_code == 409


class TestWithdrawConsent:
    async def test_withdrawal_flips_status_to_revoked_and_writes_audit(
        self, session_factory, engine: AsyncEngine, facility_id, user_id, purpose_id
    ):
        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=uuid.uuid4(), facility_id=facility_id, created_by=user_id,
                purpose_id=purpose_id, granted_by_type="patient", channel="verbal",
            )
            await db.commit()
            consent_id = record.id

        async with session_factory() as db:
            withdrawal = await service.withdraw_consent(
                db, consent_id, withdrawn_by_type="patient", withdrawn_by_user_id=user_id,
                reason="patient changed their mind", facility_id=facility_id,
            )
            await db.commit()

        assert withdrawal.consent_id == consent_id

        async with engine.begin() as conn:
            status = (
                await conn.execute(
                    text("SELECT status FROM consent_records WHERE id = :id"), {"id": consent_id}
                )
            ).scalar_one()
        assert status == "revoked"

        audit_row = await _audit_row_for(
            engine, resource_type="consent_withdrawals", resource_id=withdrawal.id
        )
        assert audit_row is not None
        assert audit_row.reason == "patient changed their mind"

    async def test_double_withdrawal_raises_409_not_500(
        self, session_factory, facility_id, user_id, purpose_id
    ):
        """trg_consent_withdrawals_flip_status rejects a withdrawal
        against an already-terminal consent (DBAPIError) — withdraw_consent()
        must translate that into a clean 409, not let a raw DB error surface."""
        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=uuid.uuid4(), facility_id=facility_id, created_by=user_id,
                purpose_id=purpose_id, granted_by_type="patient", channel="verbal",
            )
            await db.commit()
            consent_id = record.id

        async with session_factory() as db:
            await service.withdraw_consent(
                db, consent_id, withdrawn_by_type="patient", withdrawn_by_user_id=user_id,
                reason="first withdrawal", facility_id=facility_id,
            )
            await db.commit()

        async with session_factory() as db:
            with pytest.raises(HTTPException) as exc_info:
                await service.withdraw_consent(
                    db, consent_id, withdrawn_by_type="patient", withdrawn_by_user_id=user_id,
                    reason="second withdrawal", facility_id=facility_id,
                )
        assert exc_info.value.status_code == 409


class TestListConsentPurposes:
    async def test_defaults_to_active_only(self, session_factory, engine: AsyncEngine, purpose_id):
        inactive_id = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO consent_purposes (id, purpose_code, is_active) "
                    "VALUES (:id, :code, false)"
                ),
                {"id": inactive_id, "code": f"inactive_{uuid.uuid4().hex[:8]}"},
            )

        async with session_factory() as db:
            purposes = await service.list_consent_purposes(db)

        ids = {p.id for p in purposes}
        assert purpose_id in ids
        assert inactive_id not in ids


class TestGetConsentRecord:
    async def test_nonexistent_id_raises_404(self, session_factory):
        async with session_factory() as db:
            with pytest.raises(HTTPException) as exc_info:
                await service.get_consent_record(db, uuid.uuid4())
        assert exc_info.value.status_code == 404

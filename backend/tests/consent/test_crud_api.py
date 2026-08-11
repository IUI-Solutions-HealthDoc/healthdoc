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
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
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


async def _seed_patient(engine: AsyncEngine, *, facility_id, created_by) -> uuid.UUID:
    pid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO patients (id, full_name, sex, identity_path, facility_id, "
                "created_by, age_years, uhid) "
                "VALUES (:id, 'Test Patient', 'other', 'demographics_only', :facility_id, "
                ":created_by, 30, :uhid)"
            ),
            {"id": pid, "facility_id": facility_id, "created_by": created_by, "uhid": f"UHID{pid.hex[:8]}"},
        )
    return pid


async def _seed_purpose(engine: AsyncEngine, *, code: str) -> uuid.UUID:
    pid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO consent_purposes (id, purpose_code) VALUES (:id, :code)"),
            {"id": pid, "code": code},
        )
    return pid


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
        patient_id = await _seed_patient(engine, facility_id=facility_id, created_by=user_id)
        async with session_factory() as db:
            record = await service.create_consent_record(
                db,
                patient_id=patient_id,
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
        self, session_factory, engine: AsyncEngine, facility_id, user_id, purpose_id
    ):
        """The transition this endpoint must NEVER be able to perform —
        see service.py's module docstring. Only withdraw_consent() may
        produce this outcome."""
        patient_id = await _seed_patient(engine, facility_id=facility_id, created_by=user_id)
        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=patient_id, facility_id=facility_id, created_by=user_id,
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
        patient_id = await _seed_patient(engine, facility_id=facility_id, created_by=user_id)
        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=patient_id, facility_id=facility_id, created_by=user_id,
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

    async def test_withdrawal_with_scope_populates_cascade_fields(
        self, session_factory, engine: AsyncEngine, facility_id, user_id, purpose_id
    ):
        patient_id = await _seed_patient(engine, facility_id=facility_id, created_by=user_id)
        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=patient_id, facility_id=facility_id, created_by=user_id,
                purpose_id=purpose_id, granted_by_type="patient", channel="verbal",
                scope=["lab_results", "abdm_sharing"],
            )
            await db.commit()
            consent_id = record.id

        async with session_factory() as db:
            withdrawal = await service.withdraw_consent(
                db, consent_id, withdrawn_by_type="patient", withdrawn_by_user_id=user_id,
                reason=None, facility_id=facility_id,
            )
            await db.commit()

        assert withdrawal.cascaded_actions == {"lab_results": "pending", "abdm_sharing": "pending"}
        assert withdrawal.cascade_deadline is not None
        assert withdrawal.cascade_deadline > withdrawal.withdrawn_at
        assert withdrawal.cascade_completed_at is None

    async def test_withdrawal_without_scope_leaves_cascade_fields_null(
        self, session_factory, engine: AsyncEngine, facility_id, user_id, purpose_id
    ):
        patient_id = await _seed_patient(engine, facility_id=facility_id, created_by=user_id)
        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=patient_id, facility_id=facility_id, created_by=user_id,
                purpose_id=purpose_id, granted_by_type="patient", channel="verbal",
            )  # no scope
            await db.commit()
            consent_id = record.id

        async with session_factory() as db:
            withdrawal = await service.withdraw_consent(
                db, consent_id, withdrawn_by_type="patient", withdrawn_by_user_id=user_id,
                reason=None, facility_id=facility_id,
            )
            await db.commit()

        assert withdrawal.cascaded_actions is None
        assert withdrawal.cascade_deadline is None

    async def test_withdrawal_cancels_unsent_renewal_reminders(
        self, session_factory, engine: AsyncEngine, facility_id, user_id, purpose_id
    ):
        patient_id = await _seed_patient(engine, facility_id=facility_id, created_by=user_id)
        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=patient_id, facility_id=facility_id, created_by=user_id,
                purpose_id=purpose_id, granted_by_type="patient", channel="verbal",
            )
            await db.commit()
            consent_id = record.id

        unsent_id, sent_id = uuid.uuid4(), uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO consent_renewal_reminders (id, consent_id, remind_at) "
                    "VALUES (:id, :consent_id, now() + interval '5 days')"
                ),
                {"id": unsent_id, "consent_id": consent_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO consent_renewal_reminders (id, consent_id, remind_at, sent_at) "
                    "VALUES (:id, :consent_id, now() - interval '1 day', now())"
                ),
                {"id": sent_id, "consent_id": consent_id},
            )

        async with session_factory() as db:
            await service.withdraw_consent(
                db, consent_id, withdrawn_by_type="patient", withdrawn_by_user_id=user_id,
                reason=None, facility_id=facility_id,
            )
            await db.commit()

        async with engine.begin() as conn:
            remaining = set(
                (await conn.execute(
                    text("SELECT id FROM consent_renewal_reminders WHERE consent_id = :id"),
                    {"id": consent_id},
                )).scalars().all()
            )
        assert unsent_id not in remaining, "unsent reminder must be cancelled on withdrawal"
        assert sent_id in remaining, "already-sent reminders are history, not cancelled"

    async def test_double_withdrawal_raises_409_not_500(
        self, session_factory, engine: AsyncEngine, facility_id, user_id, purpose_id
    ):
        """trg_consent_withdrawals_flip_status rejects a withdrawal
        against an already-terminal consent (DBAPIError) — withdraw_consent()
        must translate that into a clean 409, not let a raw DB error surface."""
        patient_id = await _seed_patient(engine, facility_id=facility_id, created_by=user_id)
        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=patient_id, facility_id=facility_id, created_by=user_id,
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

    async def test_unrelated_db_error_is_not_swallowed_into_a_409(
        self, session_factory, engine: AsyncEngine, facility_id, user_id, purpose_id
    ):
        """A genuine FK violation (withdrawn_by_user_id pointing at a
        user that doesn't exist) is a DBAPIError too, but has nothing to
        do with the terminal-status guard -- must NOT be mislabeled as
        'already withdrawn'."""
        patient_id = await _seed_patient(engine, facility_id=facility_id, created_by=user_id)
        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=patient_id, facility_id=facility_id, created_by=user_id,
                purpose_id=purpose_id, granted_by_type="patient", channel="verbal",
            )
            await db.commit()
            consent_id = record.id

        async with session_factory() as db:
            # IntegrityError specifically, not just "any Exception" --
            # a broad catch here would also pass for an unrelated bug
            # (e.g. a missing table) for the wrong reason.
            with pytest.raises(IntegrityError):
                await service.withdraw_consent(
                    db, consent_id, withdrawn_by_type="patient",
                    withdrawn_by_user_id=uuid.uuid4(),  # no such user
                    reason="bogus withdrawer", facility_id=facility_id,
                )


class TestListConsentRecordsForPatient:
    async def test_facility_scoping_excludes_cross_facility_records(
        self, session_factory, engine: AsyncEngine, facility_id, second_facility_id, user_id, purpose_id
    ):
        patient_id = await _seed_patient(engine, facility_id=facility_id, created_by=user_id)
        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=patient_id, facility_id=facility_id, created_by=user_id,
                purpose_id=purpose_id, granted_by_type="patient", channel="verbal",
            )
            await db.commit()

        async with session_factory() as db:
            same_facility = await service.list_consent_records_for_patient(
                db, patient_id, facility_id=facility_id
            )
        assert {r.id for r in same_facility} == {record.id}

        async with session_factory() as db:
            cross_facility = await service.list_consent_records_for_patient(
                db, patient_id, facility_id=second_facility_id
            )
        assert cross_facility == []


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


class TestFindActiveConsent:
    async def test_finds_matching_granted_consent(
        self, session_factory, engine: AsyncEngine, facility_id, user_id
    ):
        purpose_code = f"direct_treatment_{uuid.uuid4().hex[:8]}"
        purpose = await _seed_purpose(engine, code=purpose_code)
        patient_id = await _seed_patient(engine, facility_id=facility_id, created_by=user_id)
        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=patient_id, facility_id=facility_id, created_by=user_id,
                purpose_id=purpose, granted_by_type="patient", channel="verbal",
            )
            await db.commit()

        async with session_factory() as db:
            found = await service.find_active_consent(
                db, patient_id=patient_id, purpose_code=purpose_code
            )
        assert found is not None
        assert found.id == record.id

    async def test_no_match_returns_none(self, session_factory, facility_id):
        async with session_factory() as db:
            found = await service.find_active_consent(
                db, patient_id=uuid.uuid4(), purpose_code="no-such-purpose"
            )
        assert found is None

    async def test_ignores_non_granted_status(
        self, session_factory, engine: AsyncEngine, facility_id, user_id
    ):
        purpose_code = f"direct_treatment_{uuid.uuid4().hex[:8]}"
        purpose = await _seed_purpose(engine, code=purpose_code)
        patient_id = await _seed_patient(engine, facility_id=facility_id, created_by=user_id)
        async with session_factory() as db:
            await service.create_consent_record(
                db, patient_id=patient_id, facility_id=facility_id, created_by=user_id,
                purpose_id=purpose, granted_by_type="patient", channel="abdm_consent_manager",
                status="requested",
            )
            await db.commit()

        async with session_factory() as db:
            found = await service.find_active_consent(
                db, patient_id=patient_id, purpose_code=purpose_code
            )
        assert found is None

    async def test_ignores_expired_consent(
        self, session_factory, engine: AsyncEngine, facility_id, user_id
    ):
        purpose_code = f"direct_treatment_{uuid.uuid4().hex[:8]}"
        purpose = await _seed_purpose(engine, code=purpose_code)
        patient_id = await _seed_patient(engine, facility_id=facility_id, created_by=user_id)
        async with session_factory() as db:
            await service.create_consent_record(
                db, patient_id=patient_id, facility_id=facility_id, created_by=user_id,
                purpose_id=purpose, granted_by_type="patient", channel="verbal",
                expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
            await db.commit()

        async with session_factory() as db:
            found = await service.find_active_consent(
                db, patient_id=patient_id, purpose_code=purpose_code
            )
        assert found is None


class TestGetConsentRecord:
    async def test_nonexistent_id_raises_404(self, session_factory):
        async with session_factory() as db:
            with pytest.raises(HTTPException) as exc_info:
                await service.get_consent_record(db, uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_facility_scoping_blocks_cross_facility_access(
        self, session_factory, engine: AsyncEngine, facility_id, second_facility_id, user_id, purpose_id
    ):
        patient_id = await _seed_patient(engine, facility_id=facility_id, created_by=user_id)
        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=patient_id, facility_id=facility_id, created_by=user_id,
                purpose_id=purpose_id, granted_by_type="patient", channel="verbal",
            )
            await db.commit()
            consent_id = record.id

        async with session_factory() as db:
            found = await service.get_consent_record(db, consent_id, facility_id=facility_id)
        assert found.id == consent_id

        async with session_factory() as db:
            with pytest.raises(HTTPException) as exc_info:
                await service.get_consent_record(db, consent_id, facility_id=second_facility_id)
        assert exc_info.value.status_code == 404


class TestGetConsentRecordRouteLogsBeforeDenial:
    """One deliberate exception to this file's service-layer-only
    convention (see module docstring). Dependency ORDER inside a route's
    dependencies=[] list is invisible to a test that calls a service or
    router function directly -- it only exists at FastAPI's actual
    routing layer. A real regression shipped here once already
    (require_roles listed before log_patient_data_access in the same
    list, so a 403 pre-empted the log write) -- this goes through a
    real, minimal FastAPI app + the real TestClient so the fix is
    proven by the same mechanism that broke, not by re-deriving
    FastAPI's dependency-resolution rules by hand a second time."""

    async def test_denied_access_is_still_logged(
        self, monkeypatch, engine: AsyncEngine, session_factory, facility_id, user_id
    ):
        import httpx
        from fastapi import FastAPI

        import app.consent.access_log as access_log_module
        from app.auth.deps import AuthUser, get_current_user
        from app.consent.router import router as consent_router

        # log_patient_data_access opens its OWN SessionLocal (see
        # access_log.py's module docstring) -- same monkeypatch tests/
        # consent/test_access_log.py already uses.
        monkeypatch.setattr(access_log_module, "SessionLocal", session_factory)

        async with engine.begin() as conn:
            sub = (
                await conn.execute(
                    text("SELECT keycloak_sub FROM users WHERE id = :id"), {"id": user_id}
                )
            ).scalar_one()

        app = FastAPI()  # bare app, no lifespan/crypto-key validation from app.main
        app.include_router(consent_router)
        # A role NOT in _CONSENT_VIEW_ROLES ("auditor", "admin", "doctor")
        # -- guarantees require_roles denies with 403.
        app.dependency_overrides[get_current_user] = lambda: AuthUser(
            sub=sub, username="tester", roles=["pharmacist"]
        )

        patient_id = uuid.uuid4()
        consent_id = uuid.uuid4()

        # httpx.AsyncClient(transport=ASGITransport(...)), NOT
        # fastapi.testclient.TestClient: TestClient drives the ASGI app
        # through anyio's sync-to-async thread portal, a DIFFERENT event
        # loop than pytest-asyncio's `engine` fixture -- log_patient_data_
        # access's own DB write then crosses event loops and silently
        # falls back to the fallback FILE instead of data_access_log,
        # which this test can't see. AsyncClient + ASGITransport runs the
        # whole request in-process on THIS test's own event loop.
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/consent/patients/{patient_id}/records/{consent_id}")

        assert response.status_code == 403

        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT patient_id, resource_type FROM data_access_log "
                        "WHERE user_id = :uid ORDER BY accessed_at DESC LIMIT 1"
                    ),
                    {"uid": user_id},
                )
            ).one_or_none()

        assert row is not None, (
            "the 403 pre-empted log_patient_data_access -- this is the exact "
            "regression this route was restructured to fix"
        )
        assert str(row.patient_id) == str(patient_id)
        assert row.resource_type == "consent_records"

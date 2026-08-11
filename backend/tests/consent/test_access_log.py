"""
Tests for app/consent/access_log.py -- the log_patient_data_access
dependency factory.

Repo path: backend/tests/consent/test_access_log.py

Happy-path test runs against the real test DB (engine/session_factory/
user_id fixtures from conftest.py), since access_log.py's whole design
is "open its own SessionLocal, commit for real, independent of the
caller's transaction" -- rolling that back to inspect it would test the
opposite of what the code actually does. The two failure paths
(missing patient_id, DB write failure) are forced deterministically via
monkeypatch rather than a real Postgres outage, which would be flaky
and slow to induce -- the thing under test there is access_log.py's own
control flow, not Postgres's availability.

access_log.py opens `app.consent.access_log.SessionLocal()` rather than
using a request-scoped session (see that file's docstring for why).
`bind_access_log_to_test_engine` monkeypatches that module-level
SessionLocal to session_factory (bound to this test's engine), so the
dependency's real commit lands in the SAME database this test then
queries to assert against.
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.deps import AuthUser
from app.consent import service
from app.consent.access_log import log_patient_data_access

pytestmark = pytest.mark.asyncio


def _fake_request(*, path_params: dict, method: str = "GET", path: str = "/test") -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "path_params": path_params,
        "query_string": b"",
        "headers": [],
    }
    req = Request(scope)
    req._path_params = path_params
    return req


@pytest.fixture
def bind_access_log_to_test_engine(monkeypatch, session_factory):
    import app.consent.access_log as access_log_module

    monkeypatch.setattr(access_log_module, "SessionLocal", session_factory)
    yield


class TestHappyPath:
    async def test_writes_a_data_access_log_row(
        self, engine: AsyncEngine, bind_access_log_to_test_engine, user_id
    ):
        patient_id = uuid.uuid4()

        # access_log.py resolves users.id via keycloak_sub -- the
        # user_id fixture already wrote keycloak_sub=f"consent-test-{uid}",
        # so build the AuthUser to match exactly.
        async with engine.begin() as conn:
            sub = (
                await conn.execute(
                    text("SELECT keycloak_sub FROM users WHERE id = :id"), {"id": user_id}
                )
            ).scalar_one()

        user = AuthUser(sub=sub, username="doc", roles=["doctor"])
        dependency = log_patient_data_access(
            resource_type="patients", purpose_code="direct_treatment"
        )
        request = _fake_request(path_params={"patient_id": str(patient_id)})

        await dependency(request, user)

        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT user_id, role, resource_type, purpose_code "
                        "FROM data_access_log WHERE patient_id = :pid"
                    ),
                    {"pid": patient_id},
                )
            ).mappings().one()

        assert row["user_id"] == user_id
        assert row["role"] == "doctor"
        assert row["resource_type"] == "patients"
        assert row["purpose_code"] == "direct_treatment"


class TestConsentLinking:
    """B7-W5-01: data_access_log.consent_id / consent_verified are now
    resolved against a real consent_records row, not always NULL."""

    async def test_active_consent_populates_consent_id_and_verified_true(
        self, engine: AsyncEngine, bind_access_log_to_test_engine, session_factory,
        user_id, facility_id, purpose_id,
    ):
        patient_id = uuid.uuid4()
        async with engine.begin() as conn:
            purpose_code = (
                await conn.execute(
                    text("SELECT purpose_code FROM consent_purposes WHERE id = :id"), {"id": purpose_id}
                )
            ).scalar_one()

        async with session_factory() as db:
            record = await service.create_consent_record(
                db, patient_id=patient_id, facility_id=facility_id, created_by=user_id,
                purpose_id=purpose_id, granted_by_type="patient", channel="verbal",
            )
            await db.commit()

        async with engine.begin() as conn:
            sub = (
                await conn.execute(
                    text("SELECT keycloak_sub FROM users WHERE id = :id"), {"id": user_id}
                )
            ).scalar_one()

        user = AuthUser(sub=sub, username="doc", roles=["doctor"])
        dependency = log_patient_data_access(resource_type="patients", purpose_code=purpose_code)
        request = _fake_request(path_params={"patient_id": str(patient_id)})

        await dependency(request, user)

        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text("SELECT consent_id, consent_verified FROM data_access_log WHERE patient_id = :pid"),
                    {"pid": patient_id},
                )
            ).mappings().one()

        assert row["consent_id"] == record.id
        assert row["consent_verified"] is True

    async def test_no_consent_and_required_sets_verified_false(
        self, engine: AsyncEngine, bind_access_log_to_test_engine, user_id
    ):
        patient_id = uuid.uuid4()
        async with engine.begin() as conn:
            sub = (
                await conn.execute(
                    text("SELECT keycloak_sub FROM users WHERE id = :id"), {"id": user_id}
                )
            ).scalar_one()

        user = AuthUser(sub=sub, username="doc", roles=["doctor"])
        dependency = log_patient_data_access(
            resource_type="patients", purpose_code="no_matching_consent", consent_required=True,
        )
        request = _fake_request(path_params={"patient_id": str(patient_id)})

        await dependency(request, user)

        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text("SELECT consent_id, consent_verified FROM data_access_log WHERE patient_id = :pid"),
                    {"pid": patient_id},
                )
            ).mappings().one()

        assert row["consent_id"] is None
        assert row["consent_verified"] is False

    async def test_no_consent_and_not_required_sets_verified_none(
        self, engine: AsyncEngine, bind_access_log_to_test_engine, user_id
    ):
        patient_id = uuid.uuid4()
        async with engine.begin() as conn:
            sub = (
                await conn.execute(
                    text("SELECT keycloak_sub FROM users WHERE id = :id"), {"id": user_id}
                )
            ).scalar_one()

        user = AuthUser(sub=sub, username="doc", roles=["doctor"])
        dependency = log_patient_data_access(
            resource_type="patients", purpose_code="no_matching_consent", consent_required=False,
        )
        request = _fake_request(path_params={"patient_id": str(patient_id)})

        await dependency(request, user)

        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text("SELECT consent_id, consent_verified FROM data_access_log WHERE patient_id = :pid"),
                    {"pid": patient_id},
                )
            ).mappings().one()

        assert row["consent_id"] is None
        assert row["consent_verified"] is None


class TestMissingPatientIdParam:
    async def test_falls_back_instead_of_silently_dropping(self, tmp_path, monkeypatch):
        """Reviewer's exact point on the original design: this path used
        to just `return` -- nothing recorded anywhere. Must now write to
        the durable fallback file instead."""
        import app.consent.access_log_fallback as fallback_module

        fallback_path = tmp_path / "fallback.jsonl"
        monkeypatch.setattr(fallback_module, "_fallback_log_path", lambda: str(fallback_path))

        dependency = log_patient_data_access(
            resource_type="patients", purpose_code="direct_treatment"
        )
        request = _fake_request(path_params={})  # no patient_id at all
        user = AuthUser(sub="sub-x", username="doc", roles=["doctor"])

        await dependency(request, user)

        assert fallback_path.exists()
        lines = fallback_path.read_text().strip().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["patient_id"] is None
        assert "missing_path_param" in row["_failure_reason"]


class TestDbWriteFailureFallback:
    async def test_db_failure_falls_back_and_does_not_raise(self, tmp_path, monkeypatch):
        """Forces the DB-write path to raise, confirms the dependency
        never propagates to the caller and writes a durable fallback
        row instead of just logging."""
        import app.consent.access_log as access_log_module
        import app.consent.access_log_fallback as fallback_module

        fallback_path = tmp_path / "fallback.jsonl"
        monkeypatch.setattr(fallback_module, "_fallback_log_path", lambda: str(fallback_path))

        class _ExplodingSessionCtx:
            async def __aenter__(self):
                raise RuntimeError("simulated DB outage")

            async def __aexit__(self, *exc_info):
                return False

        monkeypatch.setattr(access_log_module, "SessionLocal", lambda: _ExplodingSessionCtx())

        dependency = log_patient_data_access(
            resource_type="patients", purpose_code="direct_treatment"
        )
        request = _fake_request(path_params={"patient_id": str(uuid.uuid4())})
        user = AuthUser(sub="sub-y", username="doc", roles=["doctor"])

        await dependency(request, user)  # must not raise

        lines = fallback_path.read_text().strip().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert "db_write_failed" in row["_failure_reason"]
        assert "simulated DB outage" in row["_failure_reason"]


class TestRoleSelection:
    async def test_uses_shared_select_acting_role(self, monkeypatch, tmp_path):
        """Confirms access_log.py defers to app.audit.deps'
        select_acting_role rather than a second, divergent
        implementation."""
        import app.consent.access_log as access_log_module
        import app.consent.access_log_fallback as fallback_module

        monkeypatch.setattr(
            fallback_module, "_fallback_log_path",
            lambda: str(tmp_path / "fallback.jsonl"),
        )

        called_with = {}

        def _fake_select(roles):
            called_with["roles"] = roles
            return "the-selected-role"

        monkeypatch.setattr(access_log_module, "select_acting_role", _fake_select)

        class _ExplodingSessionCtx:
            async def __aenter__(self):
                raise RuntimeError("short-circuit before any real DB work")

            async def __aexit__(self, *exc_info):
                return False

        monkeypatch.setattr(access_log_module, "SessionLocal", lambda: _ExplodingSessionCtx())

        dependency = log_patient_data_access(
            resource_type="patients", purpose_code="direct_treatment"
        )
        request = _fake_request(path_params={"patient_id": str(uuid.uuid4())})
        user = AuthUser(sub="sub-z", username="doc", roles=["doctor", "admin"])

        await dependency(request, user)

        assert called_with["roles"] == ["doctor", "admin"]

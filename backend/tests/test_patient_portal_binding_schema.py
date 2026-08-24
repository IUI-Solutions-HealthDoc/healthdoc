"""Database contract for the verified patient-portal identity binding."""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="requires PostgreSQL")


async def test_patient_portal_binding_constraints_and_indexes() -> None:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            constraints = {
                row.name: row.definition.lower()
                for row in (await connection.execute(text("""
                    SELECT conname AS name, pg_get_constraintdef(oid) AS definition
                    FROM pg_constraint
                    WHERE conrelid = 'patient_portal_bindings'::regclass
                """))).all()
            }
            indexes = {
                row.name: row.definition.lower()
                for row in (await connection.execute(text("""
                    SELECT indexname AS name, indexdef AS definition
                    FROM pg_indexes WHERE tablename = 'patient_portal_bindings'
                """))).all()
            }
    finally:
        await engine.dispose()

    assert "abha_otp" in constraints["ck_patient_portal_bindings_verification_method"]
    assert "revoked_by is not null" in constraints[
        "ck_patient_portal_bindings_revocation_complete"
    ]
    for name, column in (
        ("uq_patient_portal_bindings_active_user", "user_id"),
        ("uq_patient_portal_bindings_active_patient", "patient_id"),
    ):
        assert "unique" in indexes[name]
        assert column in indexes[name]
        assert "where (revoked_at is null)" in indexes[name]

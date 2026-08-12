"""
DB-level tests for migration 0004 (consent) -- real Postgres triggers
and partitioning, not application code. Style matches
tests/audit/test_audit_logs_db.py deliberately: raw engine.begin()
blocks, DBAPIError + match on the actual RAISE EXCEPTION message,
tableoid introspection for partition placement.

Repo path: backend/tests/consent/test_0004_consent.py
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.asyncio


async def _insert_purpose(engine: AsyncEngine) -> uuid.UUID:
    pid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO consent_purposes (id, purpose_code, requires_explicit_consent) "
                "VALUES (:id, :code, true)"
            ),
            {"id": pid, "code": f"test_purpose_{pid.hex[:8]}"},
        )
    return pid


async def _insert_consent_record(
    engine: AsyncEngine, *, purpose_id: uuid.UUID, created_by: uuid.UUID, status: str = "granted"
) -> uuid.UUID:
    cid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO consent_records
                    (id, patient_id, purpose_id, granted_by_type, channel, status, created_by)
                VALUES
                    (:id, :patient_id, :purpose_id, 'patient', 'verbal', :status, :created_by)
                """
            ),
            {
                "id": cid,
                "patient_id": uuid.uuid4(),
                "purpose_id": purpose_id,
                "status": status,
                "created_by": created_by,
            },
        )
    return cid


# ---------------------------------------------------------------------
# trg_consent_records_freeze
# ---------------------------------------------------------------------

async def test_frozen_column_update_raises(engine: AsyncEngine, user_id):
    purpose_id = await _insert_purpose(engine)
    consent_id = await _insert_consent_record(engine, purpose_id=purpose_id, created_by=user_id)

    with pytest.raises(DBAPIError, match="immutable"):
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE consent_records SET guardian_name = 'changed' WHERE id = :id"),
                {"id": consent_id},
            )


async def test_status_and_status_changed_at_are_mutable(engine: AsyncEngine, user_id):
    purpose_id = await _insert_purpose(engine)
    consent_id = await _insert_consent_record(engine, purpose_id=purpose_id, created_by=user_id)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE consent_records SET status = 'denied', status_changed_at = now() "
                "WHERE id = :id"
            ),
            {"id": consent_id},
        )

    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT status FROM consent_records WHERE id = :id"), {"id": consent_id}
        )
        assert result.scalar_one() == "denied"


# ---------------------------------------------------------------------
# trg_consent_withdrawals_flip_status
# ---------------------------------------------------------------------

async def test_patient_withdrawal_flips_to_revoked(engine: AsyncEngine, user_id):
    purpose_id = await _insert_purpose(engine)
    consent_id = await _insert_consent_record(engine, purpose_id=purpose_id, created_by=user_id)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO consent_withdrawals (id, consent_id, withdrawn_by_type, withdrawn_by_user_id) "
                "VALUES (:id, :consent_id, 'patient', :user_id)"
            ),
            {"id": uuid.uuid4(), "consent_id": consent_id, "user_id": user_id},
        )

    async with engine.begin() as conn:
        status = (
            await conn.execute(
                text("SELECT status FROM consent_records WHERE id = :id"), {"id": consent_id}
            )
        ).scalar_one()
    assert status == "revoked"


async def test_system_expiry_withdrawal_flips_to_expired_not_revoked(engine: AsyncEngine, user_id):
    """The specific bug from review: system_expiry must produce 'expired',
    not 'revoked' -- different regulatory facts (lapsed vs. patient-withdrawn),
    and ConsentStatus.EXPIRED must be reachable."""
    purpose_id = await _insert_purpose(engine)
    consent_id = await _insert_consent_record(engine, purpose_id=purpose_id, created_by=user_id)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO consent_withdrawals (id, consent_id, withdrawn_by_type) "
                "VALUES (:id, :consent_id, 'system_expiry')"
            ),
            {"id": uuid.uuid4(), "consent_id": consent_id},
        )

    async with engine.begin() as conn:
        status = (
            await conn.execute(
                text("SELECT status FROM consent_records WHERE id = :id"), {"id": consent_id}
            )
        ).scalar_one()
    assert status == "expired"


async def test_withdrawal_against_terminal_consent_raises(engine: AsyncEngine, user_id):
    purpose_id = await _insert_purpose(engine)
    consent_id = await _insert_consent_record(
        engine, purpose_id=purpose_id, created_by=user_id, status="denied"
    )

    with pytest.raises(DBAPIError, match="terminal status"):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO consent_withdrawals (id, consent_id, withdrawn_by_type) "
                    "VALUES (:id, :consent_id, 'patient')"
                ),
                {"id": uuid.uuid4(), "consent_id": consent_id},
            )


# ---------------------------------------------------------------------
# data_access_log append-only + DEFAULT partition
# ---------------------------------------------------------------------

async def _insert_access_log_row(engine: AsyncEngine, user_id, **overrides):
    columns = {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "resource_type": "patients",
        "patient_id": uuid.uuid4(),
        "access_channel": "api",
        **overrides,
    }
    col_names = ", ".join(columns)
    placeholders = ", ".join(f":{k}" for k in columns)
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                f"INSERT INTO data_access_log ({col_names}) VALUES ({placeholders}) "
                f"RETURNING id, accessed_at"
            ),
            columns,
        )
        return result.one()


async def test_update_on_data_access_log_raises(engine: AsyncEngine, user_id):
    row = await _insert_access_log_row(engine, user_id)
    with pytest.raises(DBAPIError, match="append-only"):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE data_access_log SET role = 'changed' "
                    "WHERE id = :id AND accessed_at = :accessed_at"
                ),
                {"id": row.id, "accessed_at": row.accessed_at},
            )


async def test_delete_on_data_access_log_raises(engine: AsyncEngine, user_id):
    row = await _insert_access_log_row(engine, user_id)
    with pytest.raises(DBAPIError, match="append-only"):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM data_access_log WHERE id = :id AND accessed_at = :accessed_at"
                ),
                {"id": row.id, "accessed_at": row.accessed_at},
            )


async def test_row_outside_provisioned_months_lands_in_default_partition(
    engine: AsyncEngine, user_id
):
    far_future = datetime.now(timezone.utc) + timedelta(days=400)
    row = await _insert_access_log_row(engine, user_id, accessed_at=far_future)

    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT tableoid::regclass::text FROM data_access_log "
                "WHERE id = :id AND accessed_at = :accessed_at"
            ),
            {"id": row.id, "accessed_at": far_future},
        )
        partition = result.scalar_one()

    assert partition == "data_access_log_default", (
        f"expected the out-of-range row to land in data_access_log_default, "
        f"got {partition!r} -- did the insert fail instead of falling "
        f"through to DEFAULT?"
    )


# ---------------------------------------------------------------------
# break_glass_grants.justification CHECK
# ---------------------------------------------------------------------

async def test_short_justification_raises(engine: AsyncEngine, user_id):
    with pytest.raises(DBAPIError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO break_glass_grants
                        (id, patient_id, granted_to_user_id, justification, expires_at)
                    VALUES
                        (:id, :patient_id, :user_id, 'too short', now() + interval '2 hours')
                    """
                ),
                {"id": uuid.uuid4(), "patient_id": uuid.uuid4(), "user_id": user_id},
            )


async def test_sufficient_justification_is_accepted(engine: AsyncEngine, user_id):
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO break_glass_grants
                    (id, patient_id, granted_to_user_id, justification, expires_at)
                VALUES
                    (:id, :patient_id, :user_id,
                     'Unconscious patient, no next-of-kin reachable, need history now',
                     now() + interval '2 hours')
                """
            ),
            {"id": uuid.uuid4(), "patient_id": uuid.uuid4(), "user_id": user_id},
        )  # must not raise

"""
DB-level tests for migration 0003 -- these exercise real Postgres
triggers and partitioning, not application code. Covers the four
"minimum before merge" items from Tech Lead's review that are about the
schema itself.

Repo path: backend/tests/audit/test_audit_logs_db.py
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.asyncio


async def _insert_audit_row(engine: AsyncEngine, facility_id, **overrides):
    """Minimal valid audit_logs INSERT; returns (id, created_at, chain_seq)."""
    columns = {
        "facility_id": facility_id,
        "action": "create",
        "resource_type": "test_resource",
        **overrides,
    }
    col_names = ", ".join(columns)
    placeholders = ", ".join(f":{k}" for k in columns)
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                f"INSERT INTO audit_logs ({col_names}) VALUES ({placeholders}) "
                f"RETURNING id, created_at, chain_seq"
            ),
            columns,
        )
        return result.one()


# ---------------------------------------------------------------------
# Blocker #1 (original review): append-only enforcement
# ---------------------------------------------------------------------

async def test_update_on_audit_logs_raises(engine: AsyncEngine, facility_id):
    row = await _insert_audit_row(engine, facility_id)

    with pytest.raises(DBAPIError, match="append-only"):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE audit_logs SET reason = 'tampered' "
                    "WHERE id = :id AND created_at = :created_at"
                ),
                {"id": row.id, "created_at": row.created_at},
            )


async def test_delete_on_audit_logs_raises(engine: AsyncEngine, facility_id):
    row = await _insert_audit_row(engine, facility_id)

    with pytest.raises(DBAPIError, match="append-only"):
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM audit_logs WHERE id = :id AND created_at = :created_at"),
                {"id": row.id, "created_at": row.created_at},
            )


# ---------------------------------------------------------------------
# Blocker #1 (this review): chain_seq is gapless, not just monotonic,
# and independent per facility (the offline-sync property).
# ---------------------------------------------------------------------

async def test_chain_seq_is_monotonic_per_facility(engine: AsyncEngine, facility_id):
    seqs = [
        (await _insert_audit_row(engine, facility_id)).chain_seq for _ in range(3)
    ]
    assert seqs == [1, 2, 3]


async def test_chain_seq_has_no_gap_after_a_rollback(engine: AsyncEngine, facility_id):
    """
    The whole point of the counter-row rework: a rolled-back transaction
    must not consume a chain_seq value. With a raw Postgres SEQUENCE
    this test would fail (nextval() is not transactional) -- that's
    exactly the bug this migration fixes.
    """
    first = await _insert_audit_row(engine, facility_id)
    assert first.chain_seq == 1

    # Open a transaction, insert, then roll back WITHOUT committing.
    async with engine.connect() as conn:
        trans = await conn.begin()
        await conn.execute(
            text(
                "INSERT INTO audit_logs (facility_id, action, resource_type) "
                "VALUES (:fid, 'create', 'test_resource')"
            ),
            {"fid": facility_id},
        )
        await trans.rollback()

    second = await _insert_audit_row(engine, facility_id)
    assert second.chain_seq == 2, (
        "chain_seq skipped a value after a rollback -- the counter is "
        "leaking gaps the same way a raw SEQUENCE would, which makes a "
        "future deletion undetectable"
    )


async def test_chain_seq_is_independent_across_facilities(
    engine: AsyncEngine, facility_id, second_facility_id
):
    """
    Facilities write offline and sync independently -- one facility's
    write volume must never affect another facility's chain_seq
    numbering.
    """
    for _ in range(3):
        await _insert_audit_row(engine, facility_id)

    first_row_for_second_facility = await _insert_audit_row(engine, second_facility_id)
    assert first_row_for_second_facility.chain_seq == 1, (
        "second facility's chain_seq was not independent of the first "
        "facility's counter"
    )


async def test_facility_chain_seq_unique_constraint_exists(engine: AsyncEngine):
    """
    Confirms UNIQUE (facility_id, chain_seq, created_at) is actually on
    the table -- not an insert-a-duplicate test, because the
    BEFORE INSERT trigger always overwrites chain_seq (including on a
    partition-targeted insert, since row-level triggers on a
    partitioned table are cloned to every partition), so there's no way
    to force a real collision through normal SQL. Catalog introspection
    is the honest way to assert the constraint is there.
    """
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT array_agg(a.attname ORDER BY array_position(c.conkey, a.attnum))
                FROM pg_constraint c
                JOIN pg_attribute a
                  ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
                WHERE c.conname = 'uq_audit_logs_facility_chain_seq'
                GROUP BY c.conname
                """
            )
        )
        columns = result.scalar_one_or_none()

    assert columns == ["facility_id", "chain_seq", "created_at"]


# ---------------------------------------------------------------------
# Blocker #3 (original review): DEFAULT partition catches out-of-range
# rows instead of failing the insert (and therefore the mutation).
# ---------------------------------------------------------------------

async def test_row_outside_provisioned_months_lands_in_default_partition(
    engine: AsyncEngine, facility_id
):
    far_future = datetime.now(timezone.utc) + timedelta(days=400)  # past the 6 pre-created months

    row = await _insert_audit_row(engine, facility_id, created_at=far_future)

    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT tableoid::regclass::text FROM audit_logs "
                "WHERE id = :id AND created_at = :created_at"
            ),
            {"id": row.id, "created_at": far_future},
        )
        partition = result.scalar_one()

    assert partition == "audit_logs_default", (
        f"expected the out-of-range row to land in audit_logs_default, "
        f"got {partition!r} -- did the insert fail instead of falling "
        f"through to DEFAULT?"
    )

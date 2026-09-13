"""Exercise upgrade/downgrade on a connection-local PostgreSQL shadow table."""

import importlib

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integrations.test_abdm_jobs_postgres import pg_jobs as pg_jobs_fixture

pg_jobs = pg_jobs_fixture


async def test_mediated_reply_migration_preserves_evidence(pg_jobs, monkeypatch):
    sessions, _ = pg_jobs
    migration = importlib.import_module("migrations.versions.0070_abdm_mediated_confirmation")
    async with sessions() as db:
        await db.execute(text(
            "CREATE TEMP TABLE abdm_callback_replies (id integer PRIMARY KEY, "
            "kind varchar(50) NOT NULL, CONSTRAINT abdm_callback_reply_kind "
            "CHECK (kind IN ('hip_consent','hip_request','hiu_consent'))) ON COMMIT DROP"
        ))
        connection = await db.connection()

        def run(sync_connection, operation):
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(sync_connection)))
            operation()

        await db.execute(text("INSERT INTO abdm_callback_replies VALUES (1, 'hip_consent')"))
        await connection.run_sync(run, migration.upgrade)
        await connection.run_sync(run, migration.downgrade)
        await connection.run_sync(run, migration.upgrade)
        await db.execute(text("INSERT INTO abdm_callback_replies VALUES (2, 'hip_link_confirm')"))
        with pytest.raises(DBAPIError, match="check constraint"):
            async with connection.begin_nested():
                await db.execute(text("INSERT INTO abdm_callback_replies VALUES (3, 'unknown')"))
        with pytest.raises(DBAPIError, match="M2 confirmation evidence exists"):
            async with connection.begin_nested():
                await connection.run_sync(run, migration.downgrade)
        assert (await db.execute(text("SELECT id, kind FROM abdm_callback_replies ORDER BY id"))).all() == [
            (1, "hip_consent"), (2, "hip_link_confirm")
        ]
        await db.rollback()  # Drops only this connection's temporary table.


async def test_encrypted_reply_migration_roundtrip_preserves_rows(pg_jobs, monkeypatch):
    sessions, _ = pg_jobs
    migration = importlib.import_module("migrations.versions.0071_abdm_m2_reply_recovery")
    async with sessions() as db:
        await db.execute(text(
            "CREATE TEMP TABLE abdm_callback_replies (id integer PRIMARY KEY, kind varchar(50) NOT NULL, "
            "CONSTRAINT abdm_callback_reply_kind CHECK (kind IN "
            "('hip_consent','hip_request','hiu_consent','hip_link_confirm'))) ON COMMIT DROP"
        ))
        connection = await db.connection()

        def run(sync_connection, operation):
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(sync_connection)))
            operation()

        await db.execute(text("INSERT INTO abdm_callback_replies VALUES (1, 'hip_consent')"))
        await connection.run_sync(run, migration.upgrade)
        await connection.run_sync(run, migration.downgrade)
        await connection.run_sync(run, migration.upgrade)
        await db.execute(text("INSERT INTO abdm_callback_replies (id,kind) VALUES (2,'hip_link_init')"))
        with pytest.raises(DBAPIError, match="M2 reply evidence exists"):
            async with connection.begin_nested():
                await connection.run_sync(run, migration.downgrade)
        assert (await db.execute(text("SELECT id FROM abdm_callback_replies ORDER BY id"))).scalars().all() == [1, 2]
        await db.rollback()

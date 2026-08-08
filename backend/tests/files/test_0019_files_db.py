"""
Real-Postgres tests for migration 0019 (files, file_access_log).

Repo path: backend/tests/files/test_0019_files_db.py

Real Postgres only — SQLite/mocks can't exercise the append-only
trigger, CHECK constraints, or FK RESTRICT behavior this migration adds.
Fixtures (engine, facility_id, user_id, seed_file) live in conftest.py —
engine/facility_id naming matches tests/audit/conftest.py's fixtures of
the same name, on purpose.

Covers, one test per concern:
  - trigger blocks UPDATE and DELETE on file_access_log      (blocker 1's table)
  - CHECK rejects an invalid action                          (blocker 2, related)
  - accessed_at round-trips timezone-aware, not naive         (blocker 1)
  - facility_id / sha256 NOT NULL enforcement                 (should-fix)
  - sensitivity / owner_module accept >30 chars                (blocker 2, width)
  - the three retrofitted FKs resolve and RESTRICT holds
"""
import uuid
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from .conftest import seed_file

pytestmark = pytest.mark.asyncio


async def test_file_access_log_blocks_update(engine: AsyncEngine, facility_id, user_id):
    async with engine.begin() as conn:
        file_id = await seed_file(conn, facility_id, user_id)
        log_id = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO file_access_log (id, file_id, user_id, action) "
                "VALUES (:id, :file_id, :user_id, 'view')"
            ),
            {"id": log_id, "file_id": file_id, "user_id": user_id},
        )

    # Assert on WHY it failed, not just that it did. `Exception` alone would
    # pass if the trigger were dropped and the statement failed for any other
    # reason — a typo, a missing table, a dead connection.
    with pytest.raises(DBAPIError) as exc:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE file_access_log SET action = 'download' WHERE id = :id"),
                {"id": log_id},
            )
    assert "append-only" in str(exc.value)


async def test_file_access_log_blocks_delete(engine: AsyncEngine, facility_id, user_id):
    async with engine.begin() as conn:
        file_id = await seed_file(conn, facility_id, user_id)
        log_id = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO file_access_log (id, file_id, user_id, action) "
                "VALUES (:id, :file_id, :user_id, 'download')"
            ),
            {"id": log_id, "file_id": file_id, "user_id": user_id},
        )

    with pytest.raises(DBAPIError) as exc:
        async with engine.begin() as conn:
            await conn.execute(sa.text("DELETE FROM file_access_log WHERE id = :id"), {"id": log_id})
    assert "append-only" in str(exc.value)


async def test_file_access_log_action_check_rejects_invalid(engine: AsyncEngine, facility_id, user_id):
    async with engine.begin() as conn:
        file_id = await seed_file(conn, facility_id, user_id)

    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO file_access_log (file_id, user_id, action) "
                    "VALUES (:file_id, :user_id, 'peek')"
                ),
                {"file_id": file_id, "user_id": user_id},
            )


async def test_accessed_at_round_trips_timezone_aware(engine: AsyncEngine, facility_id, user_id):
    async with engine.begin() as conn:
        file_id = await seed_file(conn, facility_id, user_id)
        await conn.execute(
            sa.text(
                "INSERT INTO file_access_log (file_id, user_id, action) "
                "VALUES (:file_id, :user_id, 'view')"
            ),
            {"file_id": file_id, "user_id": user_id},
        )
        result = await conn.execute(
            sa.text("SELECT accessed_at FROM file_access_log WHERE file_id = :file_id"),
            {"file_id": file_id},
        )
        accessed_at: datetime = result.scalar_one()

    # The whole point of blocker 1 — must be aware, not naive.
    assert accessed_at.tzinfo is not None
    assert accessed_at.utcoffset() is not None


async def test_files_facility_id_not_null(engine: AsyncEngine, user_id):
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO files (bucket, object_key, sha256, uploaded_by) "
                    "VALUES ('hd-files', 'test/no-facility.pdf', :sha, :uploaded_by)"
                ),
                {"sha": "b" * 64, "uploaded_by": user_id},
            )


async def test_files_sha256_not_null(engine: AsyncEngine, facility_id, user_id):
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO files (bucket, object_key, facility_id, uploaded_by) "
                    "VALUES ('hd-files', 'test/no-sha.pdf', :facility_id, :uploaded_by)"
                ),
                {"facility_id": facility_id, "uploaded_by": user_id},
            )


async def test_files_widened_columns_accept_long_values(engine: AsyncEngine, facility_id, user_id):
    """Proves the 30->50 width fix, not just that the column exists."""
    long_value = "x" * 40  # would have overflowed varchar(30)

    async with engine.begin() as conn:
        file_id = await seed_file(
            conn, facility_id, user_id,
            sensitivity=long_value, owner_module=long_value,
        )
        result = await conn.execute(
            sa.text("SELECT sensitivity, owner_module FROM files WHERE id = :id"),
            {"id": file_id},
        )
        row = result.one()

    assert row.sensitivity == long_value
    assert row.owner_module == long_value


async def test_dangling_fks_resolve_and_restrict_holds(engine: AsyncEngine, facility_id, user_id):
    # Everything here is rolled back rather than committed, on purpose.
    # consent_records and consent_purposes are REAL tables (0004) that the
    # teardown does not drop — only the stubs get dropped. A committed
    # consent_records row would outlive `files`, and the next test's 0019
    # upgrade re-adds fk_consent_records_guardian_id_proof_file_id, which
    # Postgres validates against existing rows: the orphaned row would fail
    # that ADD CONSTRAINT and take the whole file down again.
    async with engine.connect() as conn:
        outer = await conn.begin()
        try:
            file_id = await seed_file(conn, facility_id, user_id)

            # patients is the REAL 0006 table now, not a stub — same story as
            # consent_records below, one migration later. full_name, sex,
            # identity_path, facility_id and created_by are NOT NULL with no
            # default; sex and identity_path are CHECK-constrained; and two
            # either/or CHECKs apply — ck_patients_dob_or_age and
            # ck_patients_has_identifier — so age_years and uhid are required
            # even though each column is individually nullable.
            patient_id = uuid.uuid4()
            await conn.execute(
                sa.text(
                    "INSERT INTO patients "
                    "(id, full_name, sex, identity_path, facility_id, created_by, "
                    " age_years, uhid, photo_file_id) "
                    "VALUES (:id, 'Test Patient', 'other', 'demographics_only', "
                    "        :facility_id, :created_by, 30, :uhid, :file_id)"
                ),
                {
                    "id": patient_id,
                    "facility_id": facility_id,
                    "created_by": user_id,
                    "uhid": f"IN-TS-TST001-2026-{uuid.uuid4().hex[:6]}-0",
                    "file_id": file_id,
                },
            )
            # consent_records is the REAL 0004 table now, not a stub. Five columns
            # are NOT NULL with no server_default: patient_id, purpose_id,
            # granted_by_type, channel, created_by.
            #   - granted_by_type and channel are CHECK-constrained
            #     (ck_consent_records_granted_by_type, ck_consent_records_channel),
            #     so they need real member values, not placeholders.
            #   - purpose_id is an ondelete=RESTRICT FK to consent_purposes, which
            #     0004 creates but does not seed — so seed one here.
            #   - created_by FKs users; the user_id fixture already provides one.
            #   - patient_id has no FK until 0006, so a bare UUID is fine for now.
            purpose_id = uuid.uuid4()
            await conn.execute(
                sa.text("INSERT INTO consent_purposes (id, purpose_code) VALUES (:id, :code)"),
                {"id": purpose_id, "code": f"test_{uuid.uuid4().hex[:8]}"},
            )
            consent_id = uuid.uuid4()
            await conn.execute(
                sa.text(
                    "INSERT INTO consent_records "
                    "(id, patient_id, purpose_id, granted_by_type, channel, "
                    " created_by, guardian_id_proof_file_id) "
                    "VALUES (:id, :patient_id, :purpose_id, 'patient', 'written', "
                    "        :created_by, :file_id)"
                ),
                {
                    "id": consent_id,
                    "patient_id": uuid.uuid4(),
                    "purpose_id": purpose_id,
                    "created_by": user_id,
                    "file_id": file_id,
                },
            )
            order_id = uuid.uuid4()
            await conn.execute(
                sa.text(
                    "INSERT INTO order_external_results (id, result_file_id) VALUES (:id, :file_id)"
                ),
                {"id": order_id, "file_id": file_id},
            )

            # ondelete=RESTRICT on all three retrofit FKs — deleting the
            # referenced file while these rows exist must fail. The failure is
            # scoped to a SAVEPOINT: in Postgres an error aborts the whole
            # transaction, so without begin_nested() the expected IntegrityError
            # would poison `outer` and the rollback below could not run cleanly.
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        sa.text("DELETE FROM files WHERE id = :id"), {"id": file_id}
                    )
        finally:
            await outer.rollback()

"""
DB-level tests for migration 0022a (dpdp_compliance).

Repo path: backend/tests/dpdp/test_0022a_dpdp_compliance_db.py

Real Postgres only -- the behavior under test (partial unique index,
CHECK constraints, the conditional freeze-when-closed trigger, and the
consent_records freeze trigger's new consent_manager_id coverage) is
either a real Postgres constraint or a trigger, not something SQLite or
a mock could exercise faithfully.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.asyncio


async def _seed_purpose(engine: AsyncEngine) -> uuid.UUID:
    pid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO consent_purposes (id, purpose_code) VALUES (:id, :code)"),
            {"id": pid, "code": f"dpdp_test_{uuid.uuid4().hex[:8]}"},
        )
    return pid


async def _seed_consent_record(
    engine: AsyncEngine, *, patient_id: uuid.UUID, created_by: uuid.UUID,
    consent_manager_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """consent_manager_id must be supplied HERE, at INSERT time, not set
    later via UPDATE -- trg_consent_records_freeze blocks any change to
    it (including NULL -> a value) the moment the row exists, same as
    every other non-status column on this table."""
    purpose_id = await _seed_purpose(engine)
    cid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO consent_records (id, patient_id, purpose_id, granted_by_type, "
                "channel, created_by, consent_manager_id) VALUES (:id, :patient_id, :purpose_id, "
                "'patient', 'verbal', :created_by, :cm_id)"
            ),
            {
                "id": cid, "patient_id": patient_id, "purpose_id": purpose_id,
                "created_by": created_by, "cm_id": consent_manager_id,
            },
        )
    return cid


async def _seed_consent_manager(engine: AsyncEngine) -> uuid.UUID:
    cmid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO consent_managers (id, cm_registration_id, name) "
                "VALUES (:id, :reg, 'Test CM')"
            ),
            {"id": cmid, "reg": f"CM-{uuid.uuid4().hex[:10]}"},
        )
    return cmid


# ---------------------------------------------------------------------
# data_protection_officers
# ---------------------------------------------------------------------

class TestDataProtectionOfficers:
    async def test_second_active_dpo_for_same_facility_rejected(
        self, engine: AsyncEngine, facility_id, user_id
    ):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO data_protection_officers "
                    "(facility_id, user_id, appointed_at, created_by) "
                    "VALUES (:fid, :uid, now(), :uid)"
                ),
                {"fid": facility_id, "uid": user_id},
            )

        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO data_protection_officers "
                        "(facility_id, user_id, appointed_at, created_by) "
                        "VALUES (:fid, :uid, now(), :uid)"
                    ),
                    {"fid": facility_id, "uid": user_id},
                )

    async def test_inactive_dpo_does_not_block_a_new_active_one(
        self, engine: AsyncEngine, facility_id, user_id
    ):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO data_protection_officers "
                    "(facility_id, user_id, appointed_at, is_active, created_by) "
                    "VALUES (:fid, :uid, now(), false, :uid)"
                ),
                {"fid": facility_id, "uid": user_id},
            )
            # Second, ACTIVE row for the same facility -- must succeed
            # since the first one is inactive.
            await conn.execute(
                text(
                    "INSERT INTO data_protection_officers "
                    "(facility_id, user_id, appointed_at, is_active, created_by) "
                    "VALUES (:fid, :uid, now(), true, :uid)"
                ),
                {"fid": facility_id, "uid": user_id},
            )


# ---------------------------------------------------------------------
# patient_grievances
# ---------------------------------------------------------------------

class TestPatientGrievances:
    async def test_valid_row_inserts(self, engine: AsyncEngine, facility_id, patient_id, user_id):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO patient_grievances "
                    "(grievance_number, patient_id, facility_id, grievance_type, description, "
                    "due_at, created_by) "
                    "VALUES (:num, :pid, :fid, 'access', 'test grievance', "
                    "now() + interval '90 days', :uid)"
                ),
                {"num": f"GRV-{uuid.uuid4().hex[:10]}", "pid": patient_id, "fid": facility_id, "uid": user_id},
            )

    async def test_invalid_grievance_type_rejected(
        self, engine: AsyncEngine, facility_id, patient_id, user_id
    ):
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO patient_grievances "
                        "(grievance_number, patient_id, facility_id, grievance_type, description, "
                        "due_at, created_by) "
                        "VALUES (:num, :pid, :fid, 'not_a_real_type', 'x', now(), :uid)"
                    ),
                    {"num": f"GRV-{uuid.uuid4().hex[:10]}", "pid": patient_id, "fid": facility_id, "uid": user_id},
                )

    async def test_invalid_status_rejected(self, engine: AsyncEngine, facility_id, patient_id, user_id):
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO patient_grievances "
                        "(grievance_number, patient_id, facility_id, grievance_type, description, "
                        "status, due_at, created_by) "
                        "VALUES (:num, :pid, :fid, 'access', 'x', 'not_a_real_status', now(), :uid)"
                    ),
                    {"num": f"GRV-{uuid.uuid4().hex[:10]}", "pid": patient_id, "fid": facility_id, "uid": user_id},
                )


# ---------------------------------------------------------------------
# data_breach_notifications
# ---------------------------------------------------------------------

class TestDataBreachNotifications:
    async def _seed(self, engine: AsyncEngine, *, facility_id, status: str = "open") -> uuid.UUID:
        bid = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO data_breach_notifications "
                    "(id, breach_number, detected_at, nature, status, facility_id) "
                    "VALUES (:id, :num, now(), 'test breach', :status, :fid)"
                ),
                {"id": bid, "num": f"BRC-{uuid.uuid4().hex[:10]}", "status": status, "fid": facility_id},
            )
        return bid

    async def test_mutable_while_open(self, engine: AsyncEngine, facility_id):
        breach_id = await self._seed(engine, facility_id=facility_id, status="open")
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE data_breach_notifications SET mitigation_measures = 'patched' "
                    "WHERE id = :id"
                ),
                {"id": breach_id},
            )

    async def test_frozen_once_closed_update_raises(self, engine: AsyncEngine, facility_id):
        breach_id = await self._seed(engine, facility_id=facility_id, status="closed")
        with pytest.raises(DBAPIError, match="immutable"):
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE data_breach_notifications SET nature = 'changed' WHERE id = :id"),
                    {"id": breach_id},
                )

    async def test_frozen_once_closed_delete_raises(self, engine: AsyncEngine, facility_id):
        breach_id = await self._seed(engine, facility_id=facility_id, status="closed")
        with pytest.raises(DBAPIError, match="immutable"):
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM data_breach_notifications WHERE id = :id"), {"id": breach_id}
                )

    async def test_can_still_delete_while_open(self, engine: AsyncEngine, facility_id):
        """Proves the freeze is keyed off status='closed', not a blanket
        append-only-from-creation rule -- an open, still-draft breach
        record can be corrected/removed."""
        breach_id = await self._seed(engine, facility_id=facility_id, status="open")
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM data_breach_notifications WHERE id = :id"), {"id": breach_id}
            )

    async def test_invalid_status_rejected(self, engine: AsyncEngine, facility_id):
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO data_breach_notifications "
                        "(breach_number, detected_at, nature, status, facility_id) "
                        "VALUES (:num, now(), 'x', 'not_a_real_status', :fid)"
                    ),
                    {"num": f"BRC-{uuid.uuid4().hex[:10]}", "fid": facility_id},
                )


# ---------------------------------------------------------------------
# consent_managers + consent_records.consent_manager_id
# ---------------------------------------------------------------------

class TestConsentManagers:
    async def test_duplicate_registration_id_rejected(self, engine: AsyncEngine):
        reg_id = f"CM-{uuid.uuid4().hex[:10]}"
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO consent_managers (cm_registration_id, name) VALUES (:reg, 'A')"),
                {"reg": reg_id},
            )
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text("INSERT INTO consent_managers (cm_registration_id, name) VALUES (:reg, 'B')"),
                    {"reg": reg_id},
                )

    async def test_consent_record_can_be_created_with_a_consent_manager(
        self, engine: AsyncEngine, patient_id, user_id
    ):
        cm_id = await _seed_consent_manager(engine)
        consent_id = await _seed_consent_record(
            engine, patient_id=patient_id, created_by=user_id, consent_manager_id=cm_id
        )
        async with engine.begin() as conn:
            stored = (
                await conn.execute(
                    text("SELECT consent_manager_id FROM consent_records WHERE id = :id"),
                    {"id": consent_id},
                )
            ).scalar_one()
        assert stored == cm_id

    async def test_freeze_trigger_blocks_changing_consent_manager_id_after_insert(
        self, engine: AsyncEngine, patient_id, user_id
    ):
        """The actual regression this migration exists to prevent: without
        re-declaring trg_consent_records_freeze to include
        consent_manager_id, this column would be silently exempt from the
        immutability guarantee every other consent_records column has."""
        cm_a = await _seed_consent_manager(engine)
        cm_b = await _seed_consent_manager(engine)
        consent_id = await _seed_consent_record(
            engine, patient_id=patient_id, created_by=user_id, consent_manager_id=cm_a
        )

        with pytest.raises(DBAPIError, match="immutable"):
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE consent_records SET consent_manager_id = :cm WHERE id = :id"),
                    {"cm": cm_b, "id": consent_id},
                )

    async def test_status_still_mutable_with_a_consent_manager_set(
        self, engine: AsyncEngine, patient_id, user_id
    ):
        """Confirms the freeze trigger re-declaration didn't accidentally
        also start blocking the columns it's SUPPOSED to allow."""
        cm_id = await _seed_consent_manager(engine)
        consent_id = await _seed_consent_record(
            engine, patient_id=patient_id, created_by=user_id, consent_manager_id=cm_id
        )
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE consent_records SET status = 'revoked' WHERE id = :id"),
                {"id": consent_id},
            )

    async def test_invalid_consent_manager_id_rejected_at_insert(
        self, engine: AsyncEngine, patient_id, user_id
    ):
        with pytest.raises(IntegrityError):
            await _seed_consent_record(
                engine, patient_id=patient_id, created_by=user_id, consent_manager_id=uuid.uuid4()
            )

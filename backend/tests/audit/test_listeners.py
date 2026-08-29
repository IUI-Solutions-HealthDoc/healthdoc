"""
Tests for app/audit/listeners.py's before_flush/after_flush mechanism --
the ticket's core claim ("every mutation writes audit_logs, same
transaction, rollback together") currently rests on a docstring. These
tests exercise it against a real Session and a real Postgres database.

Repo path: backend/tests/audit/test_listeners.py
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

# Importing this registers the before_flush/after_flush hooks on
# sqlalchemy.orm.Session -- without it, this whole file would pass for
# the wrong reason (nothing would fire, so "zero audit rows" would look
# like success instead of like the mechanism never having engaged).
from app.audit import listeners  # noqa: F401
from tests.audit.conftest import ScratchAuditedThing

pytestmark = pytest.mark.asyncio


async def test_opted_in_model_create_produces_exactly_one_audit_row(
    session_factory, facility_id, scratch_audited_table
):
    async with session_factory() as session:
        thing = ScratchAuditedThing(id=uuid.uuid4(), facility_id=facility_id, name="widget")
        session.add(thing)
        await session.commit()
        thing_id = thing.id

    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT count(*) FROM audit_logs "
                "WHERE facility_id = :fid AND resource_type = 'scratch_audited_things' "
                "AND action = 'create' AND resource_id = :rid"
            ),
            {"fid": facility_id, "rid": thing_id},
        )
        assert result.scalar_one() == 1


async def test_audit_row_lands_in_the_same_transaction_as_the_mutation(
    session_factory, facility_id, scratch_audited_table
):
    """
    Not just "an audit row eventually exists" -- specifically that it
    was written via the SAME flush/transaction as the business insert,
    per listeners.py's core design claim. We can't observe "same
    transaction" directly from outside, but we CAN observe its
    necessary consequence: if the session's commit is never called (we
    roll back instead), NEITHER row should exist. That's the
    distinguishing behavior a separately-committed audit write would
    get wrong.
    """
    thing_id = uuid.uuid4()

    async with session_factory() as session:
        thing = ScratchAuditedThing(id=thing_id, facility_id=facility_id, name="never saved")
        session.add(thing)
        await session.flush()  # runs before_flush/after_flush, does NOT commit
        await session.rollback()

    async with session_factory() as session:
        business_count = (
            await session.execute(
                text("SELECT count(*) FROM scratch_audited_things WHERE id = :id"),
                {"id": thing_id},
            )
        ).scalar_one()
        audit_count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_logs WHERE resource_id = :id "
                    "AND resource_type = 'scratch_audited_things'"
                ),
                {"id": thing_id},
            )
        ).scalar_one()

    assert (business_count, audit_count) == (0, 0), (
        "a rollback after flush left one of the two rows behind -- the "
        "business mutation and its audit row are not actually sharing "
        "one transaction"
    )


async def test_failing_audit_write_rolls_back_the_business_mutation(
    session_factory, scratch_audited_table
):
    """
    The ticket's core requirement, stated directly: if listeners.py
    can't resolve a NOT-NULL facility_id for the audit row, it raises
    in after_flush (see listeners.py) -- and that must take the
    business mutation down with it, not leave an unaudited row sitting
    in the table.
    """
    thing_id = uuid.uuid4()

    async with session_factory() as session:
        # facility_id=None -> listeners.py's after_flush resolves
        # audit_logs.facility_id to None and raises ValueError, since
        # that column is NOT NULL.
        thing = ScratchAuditedThing(id=thing_id, facility_id=None, name="should not persist")
        session.add(thing)
        with pytest.raises(ValueError, match="facility_id is None"):
            await session.commit()
        await session.rollback()

    async with session_factory() as session:
        business_count = (
            await session.execute(
                text("SELECT count(*) FROM scratch_audited_things WHERE id = :id"),
                {"id": thing_id},
            )
        ).scalar_one()

    assert business_count == 0, (
        "the business row survived even though its audit write failed -- "
        "audit failure is supposed to take the mutation down with it"
    )


async def test_two_mutations_in_one_transaction_produce_two_audit_rows(
    session_factory, facility_id, scratch_audited_table
):
    """Sanity check on the "exactly one row per mutation" claim at N=2, not just N=1."""
    async with session_factory() as session:
        first = ScratchAuditedThing(id=uuid.uuid4(), facility_id=facility_id, name="one")
        second = ScratchAuditedThing(id=uuid.uuid4(), facility_id=facility_id, name="two")
        session.add_all([first, second])
        await session.commit()

    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT count(*) FROM audit_logs "
                "WHERE facility_id = :fid AND resource_type = 'scratch_audited_things' "
                "AND action = 'create'"
            ),
            {"fid": facility_id},
        )
        assert result.scalar_one() == 2


# ---------------------------------------------------------------------------
# Binary columns and per-model exclusions (added with ABDM M2/M3, which brought
# the first audited models carrying encrypted key material).
# ---------------------------------------------------------------------------


def test_bytes_are_redacted_rather_than_serialised():
    """audit_logs is append-only, so a ciphertext written into it can never be
    removed — while the row it came from can be rotated or cleared. Copying one
    in would outlive the thing it describes.

    This also used to be a crash: json.dumps raised TypeError on bytes and took
    the whole flush down. A crash is not a control.
    """
    from app.audit.listeners import _json_safe

    redacted = _json_safe(b"\x00\x01secret-key-material")

    assert redacted == "<21 bytes, redacted>"
    assert "secret" not in redacted
    # The length survives because "the key changed" is a real audit fact.
    assert "21" in redacted


def test_memoryview_and_bytearray_are_redacted_too():
    """psycopg hands back memoryview for bytea, not bytes. A check that only
    caught `bytes` would pass in tests and leak in production."""
    from app.audit.listeners import _json_safe

    assert _json_safe(bytearray(b"abc")) == "<3 bytes, redacted>"
    assert _json_safe(memoryview(b"abcd")) == "<4 bytes, redacted>"


def test_excluded_fields_are_absent_from_the_snapshot_entirely():
    """Distinct from redaction: for key material even 'this field changed' is
    more than the trail should carry."""
    from app.audit.listeners import _column_snapshot
    from app.integrations.abdm.hiu.models import AbdmHiuHealthInformationRequest

    assert "private_key_encrypted" in AbdmHiuHealthInformationRequest.__audit_exclude_fields__
    assert "key_version" in AbdmHiuHealthInformationRequest.__audit_exclude_fields__

    row = AbdmHiuHealthInformationRequest(
        facility_id=uuid.uuid4(),
        artefact_id=uuid.uuid4(),
        status="requested",
        public_key_b64="cHVibGlj",
        nonce_b64="bm9uY2U=",
        key_expires_at=datetime.now(timezone.utc),
        created_by=uuid.uuid4(),
        private_key_encrypted=b"\x01ciphertext",
        key_version=1,
    )

    snapshot = _column_snapshot(row, want_old=False)

    assert "private_key_encrypted" not in snapshot
    assert "key_version" not in snapshot
    # The public half stays: which key we published is legitimately auditable.
    assert snapshot.get("public_key_b64") == "cHVibGlj"


def test_a_model_without_the_attribute_is_unaffected():
    """The exclusion is opt-in; every existing audited model must behave as before."""
    from app.audit.listeners import _column_snapshot
    from app.integrations.abdm.hip.models import AbdmCareContext

    row = AbdmCareContext(
        facility_id=uuid.uuid4(), patient_id=uuid.uuid4(),
        reference="visit-1", display="OPD visit", hi_type="OPConsultation",
        created_by=uuid.uuid4(),
    )
    snapshot = _column_snapshot(row, want_old=False)
    assert snapshot["reference"] == "visit-1"

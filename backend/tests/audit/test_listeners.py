"""
Tests for app/audit/listeners.py's before_flush/after_flush mechanism --
the ticket's core claim ("every mutation writes audit_logs, same
transaction, rollback together") currently rests on a docstring. These
tests exercise it against a real Session and a real Postgres database.

Repo path: backend/tests/audit/test_listeners.py
"""
from __future__ import annotations

import uuid

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

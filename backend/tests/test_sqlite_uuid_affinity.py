"""The SQLite fixture must keep every UUID as text, including number-like ones."""

import uuid

import pytest
from sqlalchemy import select

from app.users.models import Facility

pytestmark = pytest.mark.asyncio


async def test_a_uuid_whose_hex_reads_as_a_number_round_trips(db):
    number_like = uuid.UUID("12345678-1234-1234-1234-1234567890e1")
    db.add(Facility(id=number_like, code="NUM01", name="Number-like id", state_code="TS"))
    await db.flush()
    db.expunge_all()
    assert (await db.execute(select(Facility.id).where(Facility.code == "NUM01"))).scalar_one() == number_like

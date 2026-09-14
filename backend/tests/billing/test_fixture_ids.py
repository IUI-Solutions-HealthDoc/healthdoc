"""Fixture identifiers must not collapse UUIDs to a five-character namespace."""

import uuid
from unittest.mock import AsyncMock

from tests.billing import conftest as fixtures


async def test_default_facility_codes_do_not_collide_on_a_shared_uuid_prefix(monkeypatch):
    identifiers = iter([
        uuid.UUID("52325000-0000-4000-8000-000000000001"),
        uuid.UUID("52325000-0000-4000-8000-000000000002"),
    ])
    monkeypatch.setattr(fixtures.uuid, "uuid4", lambda: next(identifiers))
    db = AsyncMock()
    await fixtures.seed_facility(db)
    await fixtures.seed_facility(db)
    codes = [call.args[1]["code"] for call in db.execute.await_args_list]
    assert codes[0] != codes[1]
    assert all(len(code) == 20 and code.startswith("TST") for code in codes)


async def test_explicit_facility_code_is_preserved():
    db = AsyncMock()
    await fixtures.seed_facility(db, code="REVIEWED-TEST")
    assert db.execute.await_args.args[1]["code"] == "REVIEWED-TEST"

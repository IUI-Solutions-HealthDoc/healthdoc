"""Tests for THID generation — sequence naming, format, and DB path.

B2-W4-01: THID issuance for emergency patients.

Sequence tests use mocks (not the db fixture) because CREATE SEQUENCE
is Postgres-only and the suite uses SQLite for unit tests.
"""
from __future__ import annotations

import re
import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.emergency.service import (
    _current_day_str,
    _thid_sequence_name,
    _next_thid_sequence,
    generate_thid,
)


# ---------------------------------------------------------------------------
# _thid_sequence_name
# ---------------------------------------------------------------------------

def test_sequence_name_format():
    assert _thid_sequence_name("JPR001", "260714") == "seq_thid_jpr001_260714"


def test_sequence_name_differs_per_facility():
    a = _thid_sequence_name("JPR001", "260714")
    b = _thid_sequence_name("JPR002", "260714")
    assert a != b


def test_sequence_name_differs_per_day():
    a = _thid_sequence_name("JPR001", "260714")
    b = _thid_sequence_name("JPR001", "260715")
    assert a != b


def test_sequence_name_rejects_invalid_facility_code():
    with pytest.raises(ValueError, match="invalid characters"):
        _thid_sequence_name("JPR/001", "260714")


def test_sequence_name_lowercases_facility_code():
    name = _thid_sequence_name("JPR001", "260714")
    assert "JPR001" not in name
    assert "jpr001" in name


# ---------------------------------------------------------------------------
# _current_day_str
# ---------------------------------------------------------------------------

def test_current_day_str_format():
    day = _current_day_str("Asia/Kolkata")
    assert re.match(r"^\d{6}$", day), f"Expected YYMMDD, got {day!r}"


# ---------------------------------------------------------------------------
# _next_thid_sequence — DB path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_next_thid_sequence_creates_then_calls_nextval():
    """CREATE SEQUENCE IF NOT EXISTS must run before nextval — not after a
    42P01 failure. Postgres aborts the transaction on that error so the
    old catch-and-recover path could never run."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 1
    db.execute = AsyncMock(return_value=mock_result)

    result = await _next_thid_sequence(db, "JPR001", "260714")

    assert result == 1
    assert db.execute.call_count == 2

    # First call must be CREATE SEQUENCE IF NOT EXISTS
    first_call_sql = str(db.execute.call_args_list[0][0][0])
    assert "CREATE SEQUENCE" in first_call_sql.upper()
    assert "IF NOT EXISTS" in first_call_sql.upper()

    # Second call must be nextval
    second_call_sql = str(db.execute.call_args_list[1][0][0])
    assert "nextval" in second_call_sql.lower()


@pytest.mark.asyncio
async def test_next_thid_sequence_returns_incrementing_values():
    """Two calls on the same day return 1 then 2 (sequence increments)."""
    db = AsyncMock()
    counter = iter([1, 2])

    async def _fake_execute(stmt, *args, **kwargs):
        result = MagicMock()
        sql = str(stmt).upper()
        if "NEXTVAL" in sql:
            result.scalar.return_value = next(counter)
        else:
            result.scalar.return_value = None
        return result

    db.execute = _fake_execute

    first = await _next_thid_sequence(db, "JPR001", "260714")
    second = await _next_thid_sequence(db, "JPR001", "260714")

    assert first == 1
    assert second == 2


# ---------------------------------------------------------------------------
# generate_thid — format
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_thid_format():
    """TH-<FACILITY>-<YYMMDD>-<SEQ4> — seq zero-padded to 4 digits."""
    db = AsyncMock()

    async def _fake_execute(stmt, *args, **kwargs):
        result = MagicMock()
        sql = str(stmt).upper()
        if "NEXTVAL" in sql:
            result.scalar.return_value = 7
        else:
            result.scalar.return_value = None
        return result

    db.execute = _fake_execute

    thid = await generate_thid(db, facility_code="JPR001", facility_timezone="Asia/Kolkata")

    parts = thid.split("-")
    assert parts[0] == "TH"
    assert parts[1] == "JPR001"
    assert re.match(r"^\d{6}$", parts[2]), f"Expected YYMMDD, got {parts[2]!r}"
    assert parts[3] == "0007", f"Expected seq 0007, got {parts[3]!r}"


@pytest.mark.asyncio
async def test_generate_thid_seq_zero_padded_to_4():
    """Sequence number must be zero-padded to 4 digits."""
    db = AsyncMock()

    async def _fake_execute(stmt, *args, **kwargs):
        result = MagicMock()
        if "NEXTVAL" in str(stmt).upper():
            result.scalar.return_value = 1
        return result

    db.execute = _fake_execute

    thid = await generate_thid(db, facility_code="TST01")
    seq_part = thid.split("-")[-1]
    assert seq_part == "0001"
    assert len(seq_part) == 4

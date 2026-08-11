"""
Tests for app/consent/access_log_fallback.py.

Repo path: backend/tests/consent/test_access_log_fallback.py

No DB needed — this module's whole point is to work WITHOUT the DB, so
these tests deliberately don't touch Postgres at all.
"""

from __future__ import annotations

import json
import os
import uuid

from app.consent import access_log_fallback as fallback_module
from app.consent.access_log_fallback import serialise_row_for_fallback, write_fallback_row


class TestWriteFallbackRow:
    async def test_creates_parent_directory_and_appends_a_json_line(self, tmp_path, monkeypatch):
        target = tmp_path / "nested" / "dir" / "fallback.jsonl"
        monkeypatch.setattr(fallback_module, "_fallback_log_path", lambda: str(target))

        row = serialise_row_for_fallback(
            user_id=uuid.uuid4(),
            role="doctor",
            resource_type="patients",
            resource_id=None,
            patient_id=uuid.uuid4(),
            purpose_code="direct_treatment",
            access_channel="api",
            emergency_access=False,
            consent_required=None,
            consent_verified=None,
        )

        ok = await write_fallback_row(row, failure_reason="test_reason")

        assert ok is True
        assert target.exists()
        line = json.loads(target.read_text().strip())
        assert line["resource_type"] == "patients"
        assert line["_failure_reason"] == "test_reason"
        assert "_fallback_written_at" in line

    async def test_appends_multiple_rows_without_clobbering(self, tmp_path, monkeypatch):
        target = tmp_path / "fallback.jsonl"
        monkeypatch.setattr(fallback_module, "_fallback_log_path", lambda: str(target))

        for i in range(3):
            row = serialise_row_for_fallback(
                user_id=None,
                role=None,
                resource_type=f"resource_{i}",
                resource_id=None,
                patient_id=None,
                purpose_code="p",
                access_channel="api",
                emergency_access=False,
                consent_required=None,
                consent_verified=None,
            )
            await write_fallback_row(row, failure_reason=f"reason_{i}")

        lines = target.read_text().strip().splitlines()
        assert len(lines) == 3
        assert [json.loads(l)["resource_type"] for l in lines] == [
            "resource_0", "resource_1", "resource_2",
        ]

    async def test_returns_false_and_does_not_raise_when_path_is_unwritable(self, monkeypatch):
        """Last-resort case: even the fallback can't be written (e.g.
        disk full, permissions). Must not raise — the caller (access_log.py)
        has nothing else to fall back to at that point."""
        monkeypatch.setattr(
            fallback_module, "_fallback_log_path",
            lambda: "/proc/this-path-cannot-be-created/x.jsonl",
        )
        row = serialise_row_for_fallback(
            user_id=None, role=None, resource_type="patients", resource_id=None,
            patient_id=None, purpose_code="p", access_channel="api",
            emergency_access=False, consent_required=None, consent_verified=None,
        )
        ok = await write_fallback_row(row, failure_reason="test")
        assert ok is False  # did not raise, reported failure instead


class TestSerialiseRowForFallback:
    def test_uuids_become_strings(self):
        uid = uuid.uuid4()
        pid = uuid.uuid4()
        row = serialise_row_for_fallback(
            user_id=uid, role="nurse", resource_type="encounters", resource_id=None,
            patient_id=pid, purpose_code="p", access_channel="ui",
            emergency_access=True, consent_required=True, consent_verified=None,
        )
        assert row["user_id"] == str(uid)
        assert row["patient_id"] == str(pid)
        assert isinstance(row["user_id"], str)

    def test_none_ids_stay_none_not_string_none(self):
        row = serialise_row_for_fallback(
            user_id=None, role=None, resource_type="patients", resource_id=None,
            patient_id=None, purpose_code="p", access_channel="api",
            emergency_access=False, consent_required=None, consent_verified=None,
        )
        assert row["user_id"] is None
        assert row["patient_id"] is None

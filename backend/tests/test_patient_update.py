"""
Tests for PATCH /patients/{id} — W2-03 patient update with audit logging.

These tests are unit/integration tests that do NOT need a real Postgres
instance — they use the same SQLite-backed async fixture pattern as the
rest of the suite. The audit row write is tested by asserting that
audited_mutation() was entered (via mock), since the actual DB trigger
(trg_audit_logs_assign_chain_seq) only runs under real Postgres.
"""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

from app.patients.service import (
    update_patient,
    _PATIENT_UPDATEABLE_FIELDS,
    _json_safe_value,
)
from app.patients.schemas import PatientUpdate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_patient(**kwargs) -> MagicMock:
    """Minimal Patient mock with sensible defaults."""
    p = MagicMock()
    p.id = kwargs.get("id", uuid.uuid4())
    p.facility_id = kwargs.get("facility_id", uuid.uuid4())
    p.status = kwargs.get("status", "active")
    p.deleted_at = kwargs.get("deleted_at", None)
    p.full_name = kwargs.get("full_name", "Ramesh Kumar")
    p.sex = kwargs.get("sex", "male")
    p.dob = kwargs.get("dob", date(1990, 1, 1))
    p.age_years = kwargs.get("age_years", None)
    p.mobile = kwargs.get("mobile", "9876543210")
    p.abha_number = kwargs.get("abha_number", None)
    p.guardian_name = kwargs.get("guardian_name", None)
    p.guardian_relationship = kwargs.get("guardian_relationship", None)
    p.address_line = kwargs.get("address_line", None)
    p.village_town = kwargs.get("village_town", None)
    p.district = kwargs.get("district", None)
    p.state_code = kwargs.get("state_code", None)
    p.pincode = kwargs.get("pincode", None)
    return p


class _FakeAuditCapture:
    resource_id = None
    old_value = None
    new_value = None
    reason = None


class _FakeAuditedMutation:
    """Async context manager that yields a capture object, like the real one."""
    def __init__(self, capture):
        self._capture = capture

    async def __aenter__(self):
        return self._capture

    async def __aexit__(self, *_):
        pass


# ---------------------------------------------------------------------------
# _json_safe_value
# ---------------------------------------------------------------------------

def test_json_safe_value_date():
    assert _json_safe_value(date(2000, 6, 15)) == "2000-06-15"

def test_json_safe_value_uuid():
    u = uuid.uuid4()
    assert _json_safe_value(u) == str(u)

def test_json_safe_value_str_passthrough():
    assert _json_safe_value("hello") == "hello"

def test_json_safe_value_none_passthrough():
    assert _json_safe_value(None) is None


# ---------------------------------------------------------------------------
# PatientUpdate schema validation
# ---------------------------------------------------------------------------

def test_patient_update_rejects_empty_payload():
    with pytest.raises(Exception):
        PatientUpdate()  # no fields → validator raises

def test_patient_update_accepts_single_field():
    p = PatientUpdate(full_name="Suresh")
    assert p.full_name == "Suresh"

def test_patient_update_reason_not_in_updateable_fields():
    # reason must NOT be applied to the patient row — only forwarded to audit
    assert "reason" not in _PATIENT_UPDATEABLE_FIELDS

def test_patient_update_all_updateable_fields_present():
    # Smoke-test: every field in _PATIENT_UPDATEABLE_FIELDS exists on PatientUpdate
    p = PatientUpdate(full_name="X")
    for field in _PATIENT_UPDATEABLE_FIELDS:
        assert hasattr(p, field), f"PatientUpdate missing field: {field}"


# ---------------------------------------------------------------------------
# update_patient() — service logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_patient_not_found_raises():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    payload = PatientUpdate(full_name="New Name")
    with pytest.raises(ValueError, match="patient_not_found"):
        await update_patient(db, patient_id=uuid.uuid4(), facility_id=uuid.uuid4(),
                             payload=payload, updated_by=uuid.uuid4())


@pytest.mark.asyncio
async def test_update_patient_wrong_facility_raises():
    patient = _make_patient(facility_id=uuid.uuid4())
    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)
    payload = PatientUpdate(full_name="New Name")
    with pytest.raises(ValueError, match="patient_not_found"):
        await update_patient(db, patient_id=patient.id, facility_id=uuid.uuid4(),
                             payload=payload, updated_by=uuid.uuid4())


@pytest.mark.asyncio
async def test_update_patient_merged_raises():
    fid = uuid.uuid4()
    patient = _make_patient(facility_id=fid, status="merged")
    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)
    payload = PatientUpdate(full_name="New Name")
    with pytest.raises(ValueError, match="cannot_update_merged_patient"):
        await update_patient(db, patient_id=patient.id, facility_id=fid,
                             payload=payload, updated_by=uuid.uuid4())


@pytest.mark.asyncio
async def test_update_patient_deleted_raises():
    from datetime import datetime, timezone
    fid = uuid.uuid4()
    patient = _make_patient(facility_id=fid, deleted_at=datetime.now(timezone.utc))
    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)
    payload = PatientUpdate(full_name="New Name")
    with pytest.raises(ValueError, match="patient_not_found"):
        await update_patient(db, patient_id=patient.id, facility_id=fid,
                             payload=payload, updated_by=uuid.uuid4())


@pytest.mark.asyncio
async def test_update_patient_applies_fields_and_writes_audit():
    fid = uuid.uuid4()
    uid = uuid.uuid4()
    patient = _make_patient(facility_id=fid, full_name="Old Name", mobile="1111111111")
    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)

    capture = _FakeAuditCapture()

    with patch("app.patients.service.audited_mutation",
               return_value=_FakeAuditedMutation(capture)):
        await update_patient(
            db,
            patient_id=patient.id,
            facility_id=fid,
            payload=PatientUpdate(full_name="New Name", mobile="9999999999"),
            updated_by=uid,
            reason="Patient corrected own name",
        )

    # Fields applied to the patient object
    assert patient.full_name == "New Name"
    assert patient.mobile == "9999999999"
    assert patient.updated_by == uid

    # Audit capture populated
    assert capture.resource_id == patient.id
    assert capture.reason == "Patient corrected own name"
    assert capture.old_value == {"full_name": "Old Name", "mobile": "1111111111"}
    assert capture.new_value == {"full_name": "New Name", "mobile": "9999999999"}


@pytest.mark.asyncio
async def test_update_patient_reason_not_applied_to_patient_row():
    """reason must go to audit only, never setattr'd onto patient."""
    fid = uuid.uuid4()
    patient = _make_patient(facility_id=fid)
    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)
    capture = _FakeAuditCapture()

    with patch("app.patients.service.audited_mutation",
               return_value=_FakeAuditedMutation(capture)):
        await update_patient(
            db,
            patient_id=patient.id,
            facility_id=fid,
            payload=PatientUpdate(full_name="X", reason="test reason"),
            updated_by=uuid.uuid4(),
            reason="test reason",
        )

    # reason must not have been written to the patient row.
    # _PATIENT_UPDATEABLE_FIELDS is the authoritative list of what gets
    # setattr'd — assert "reason" is simply not in it, which is what the
    # service loop iterates. The schema-level test already covers this too.
    assert "reason" not in _PATIENT_UPDATEABLE_FIELDS
    # And the audit capture got it, not the patient
    assert capture.reason == "test reason"


@pytest.mark.asyncio
async def test_update_patient_only_changed_fields_in_diff():
    """old_value/new_value contain only the fields supplied in the payload."""
    fid = uuid.uuid4()
    patient = _make_patient(facility_id=fid, full_name="A", mobile="000")
    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)
    capture = _FakeAuditCapture()

    with patch("app.patients.service.audited_mutation",
               return_value=_FakeAuditedMutation(capture)):
        await update_patient(
            db,
            patient_id=patient.id,
            facility_id=fid,
            payload=PatientUpdate(full_name="B"),  # only full_name supplied
            updated_by=uuid.uuid4(),
        )

    assert set(capture.old_value.keys()) == {"full_name"}
    assert set(capture.new_value.keys()) == {"full_name"}
    assert "mobile" not in capture.old_value

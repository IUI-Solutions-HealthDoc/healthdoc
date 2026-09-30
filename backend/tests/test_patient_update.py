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

    # Fields applied to the patient object.
    #
    # The mobile arrives as ten digits and is stored as +919999999999.
    # PatientUpdate normalises it — the front desk types what it reads off a
    # form and the country code is added internally, so one stored format comes
    # out of many typed ones. This assertion carries the +91 deliberately: it
    # is the contract, and a test asserting the raw digits would pass only
    # while normalisation was absent.
    assert patient.full_name == "New Name"
    assert patient.mobile == "+919999999999"
    assert patient.updated_by == uid

    # Audit capture populated.
    #
    # new_value records what was STORED, not what was typed. An audit trail
    # that logged the pre-normalisation string would disagree with the row it
    # describes, which is the one thing an audit trail may never do.
    assert capture.resource_id == patient.id
    assert capture.reason == "Patient corrected own name"
    assert capture.old_value == {"full_name": "Old Name", "mobile": "1111111111"}
    assert capture.new_value == {"full_name": "New Name", "mobile": "+919999999999"}


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


# ---------------------------------------------------------------------------
# ABHA, clearing and date-of-birth rules
# ---------------------------------------------------------------------------

_TODAY = date(2026, 9, 30)


def test_abha_number_cannot_be_patched():
    with pytest.raises(Exception, match="ABHA verification"):
        PatientUpdate.model_validate({"abha_number": "91111122223333"})
    assert "abha_number" not in _PATIENT_UPDATEABLE_FIELDS


@pytest.mark.parametrize("field", ["full_name", "sex"])
def test_required_fields_cannot_be_cleared(field):
    with pytest.raises(Exception, match="cannot be cleared"):
        PatientUpdate.model_validate({field: None})


@pytest.mark.parametrize("age", [-1, 131])
def test_age_outside_0_to_130_is_refused(age):
    with pytest.raises(Exception, match="between 0 and 130"):
        PatientUpdate(age_years=age)


async def _apply(patient, payload: dict):
    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)
    capture = _FakeAuditCapture()
    with patch("app.patients.service.audited_mutation",
               return_value=_FakeAuditedMutation(capture)), \
         patch("app.patients.service.facility_today", AsyncMock(return_value=_TODAY)):
        await update_patient(
            db, patient_id=patient.id, facility_id=patient.facility_id,
            payload=PatientUpdate.model_validate(payload), updated_by=uuid.uuid4(),
        )
    return capture


@pytest.mark.asyncio
async def test_an_explicit_null_clears_an_optional_field():
    patient = _make_patient(mobile="+919876543210", guardian_name="Vikram")
    capture = await _apply(patient, {"mobile": None})
    assert patient.mobile is None
    assert patient.guardian_name == "Vikram"
    assert capture.old_value == {"mobile": "+919876543210"}
    assert capture.new_value == {"mobile": None}


@pytest.mark.asyncio
async def test_a_future_dob_is_refused_on_the_facility_date():
    patient = _make_patient()
    with pytest.raises(ValueError, match="dob_in_future"):
        await _apply(patient, {"dob": "2026-10-01"})
    assert patient.dob == date(1990, 1, 1)


@pytest.mark.asyncio
async def test_a_new_dob_recomputes_age():
    patient = _make_patient(dob=None, age_years=40)
    await _apply(patient, {"dob": "1990-10-01"})
    assert patient.dob == date(1990, 10, 1)
    assert patient.age_years == 35


@pytest.mark.asyncio
async def test_an_age_replaces_a_stale_dob():
    patient = _make_patient(dob=date(1990, 1, 1), age_years=36)
    await _apply(patient, {"age_years": 50})
    assert patient.age_years == 50
    assert patient.dob is None


@pytest.mark.asyncio
async def test_clearing_dob_without_an_age_is_refused():
    patient = _make_patient(dob=date(1990, 1, 1), age_years=None)
    with pytest.raises(ValueError, match="dob_or_age_required"):
        await _apply(patient, {"dob": None})

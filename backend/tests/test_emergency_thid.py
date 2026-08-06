"""Emergency module tests — THID generation (pure logic) + W5-01 promote/unmerge."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.emergency.service import (
    _thid_sequence_name, _current_day_str,
    request_promotion, approve_promotion, unmerge_promotion,
)
from app.emergency.schemas import EmergencyPatientCreate, PromotionRequest, UnmergeRequest


# ---------------------------------------------------------------------------
# THID generation — pure logic (original tests, unchanged)
# ---------------------------------------------------------------------------

def test_thid_sequence_name_format():
    name = _thid_sequence_name("JPR001", "260714")
    assert name == "seq_thid_jpr001_260714"


def test_thid_sequence_name_differs_per_facility():
    a = _thid_sequence_name("JPR001", "260714")
    b = _thid_sequence_name("DEL002", "260714")
    assert a != b


def test_thid_sequence_name_differs_per_day():
    a = _thid_sequence_name("JPR001", "260714")
    b = _thid_sequence_name("JPR001", "260715")
    assert a != b


def test_thid_sequence_name_rejects_invalid_facility_code():
    with pytest.raises(ValueError):
        _thid_sequence_name("JPR001; DROP TABLE patients;--", "260714")


def test_current_day_str_is_six_digits():
    result = _current_day_str()
    assert len(result) == 6
    int(result)  # raises ValueError if not numeric


# ---------------------------------------------------------------------------
# EmergencyPatientCreate schema
# ---------------------------------------------------------------------------

def test_emergency_patient_create_requires_age_years():
    with pytest.raises(Exception):
        EmergencyPatientCreate(sex="male")  # age_years missing


def test_emergency_patient_create_accepts_unknown_name():
    p = EmergencyPatientCreate(sex="female", age_years=30)
    assert p.full_name is None


def test_emergency_patient_create_no_facility_id_field():
    # facility_id must not be on the schema — sourced from current_db_user
    assert not hasattr(EmergencyPatientCreate(sex="male", age_years=25), "facility_id")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_patient(*, identity_path="thid", status="active", uhid=None,
                  facility_id=None, deleted_at=None) -> MagicMock:
    p = MagicMock()
    p.id = uuid.uuid4()
    p.facility_id = facility_id or uuid.uuid4()
    p.identity_path = identity_path
    p.status = status
    p.uhid = uhid
    p.thid = f"TH-JPR001-260714-0001"
    p.deleted_at = deleted_at
    return p


def _make_merge_log(*, source_type="thid", status="pending",
                    requested_by=None, approved_by=None,
                    source_patient_id=None) -> MagicMock:
    log = MagicMock()
    log.id = uuid.uuid4()
    log.source_type = source_type
    log.status = status
    log.requested_by = requested_by or uuid.uuid4()
    log.approved_by = approved_by
    log.source_patient_id = source_patient_id or uuid.uuid4()
    log.reason = None
    return log


class _FakeAuditCapture:
    resource_id = None
    old_value = None
    new_value = None
    reason = None


class _FakeAuditedMutation:
    def __init__(self, capture):
        self._capture = capture
    async def __aenter__(self):
        return self._capture
    async def __aexit__(self, *_):
        pass


# ---------------------------------------------------------------------------
# request_promotion()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_promotion_patient_not_found():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(ValueError, match="patient_not_found"):
        await request_promotion(db, patient_id=uuid.uuid4(),
                                facility_id=uuid.uuid4(), reason=None,
                                requested_by=uuid.uuid4())


@pytest.mark.asyncio
async def test_request_promotion_wrong_facility():
    patient = _make_patient(facility_id=uuid.uuid4())
    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)
    with pytest.raises(ValueError, match="patient_not_found"):
        await request_promotion(db, patient_id=patient.id,
                                facility_id=uuid.uuid4(), reason=None,
                                requested_by=uuid.uuid4())


@pytest.mark.asyncio
async def test_request_promotion_not_thid_patient():
    fid = uuid.uuid4()
    patient = _make_patient(identity_path="demographics_only", facility_id=fid)
    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)
    with pytest.raises(ValueError, match="patient_not_thid"):
        await request_promotion(db, patient_id=patient.id,
                                facility_id=fid, reason=None,
                                requested_by=uuid.uuid4())


@pytest.mark.asyncio
async def test_request_promotion_merged_patient_rejected():
    fid = uuid.uuid4()
    patient = _make_patient(status="merged", facility_id=fid)
    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)
    with pytest.raises(ValueError, match="patient_not_active"):
        await request_promotion(db, patient_id=patient.id,
                                facility_id=fid, reason=None,
                                requested_by=uuid.uuid4())


@pytest.mark.asyncio
async def test_request_promotion_duplicate_pending():
    fid = uuid.uuid4()
    patient = _make_patient(facility_id=fid)
    existing_log = MagicMock()
    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)
    # execute().scalar_one_or_none() returns existing log
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=existing_log)
    ))
    with pytest.raises(ValueError, match="promotion_already_pending"):
        await request_promotion(db, patient_id=patient.id,
                                facility_id=fid, reason=None,
                                requested_by=uuid.uuid4())


# ---------------------------------------------------------------------------
# approve_promotion()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_promotion_self_approval_blocked():
    requester = uuid.uuid4()
    fid = uuid.uuid4()
    patient = _make_patient(facility_id=fid)
    merge_log = _make_merge_log(status="pending", requested_by=requester,
                                source_patient_id=patient.id)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=merge_log)
    ))
    db.get = AsyncMock(return_value=patient)
    with pytest.raises(ValueError, match="self_approval_not_allowed"):
        await approve_promotion(db, merge_log_id=merge_log.id,
                                facility_id=fid, approved_by=requester,
                                state_code="RJ", facility_code="JPR001")


@pytest.mark.asyncio
async def test_approve_promotion_not_pending():
    fid = uuid.uuid4()
    merge_log = _make_merge_log(status="approved")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=merge_log)
    ))
    with pytest.raises(ValueError, match="not_pending"):
        await approve_promotion(db, merge_log_id=merge_log.id,
                                facility_id=fid, approved_by=uuid.uuid4(),
                                state_code="RJ", facility_code="JPR001")


@pytest.mark.asyncio
async def test_approve_promotion_not_thid_type():
    fid = uuid.uuid4()
    merge_log = _make_merge_log(status="pending", source_type="duplicate_uhid")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=merge_log)
    ))
    with pytest.raises(ValueError, match="not_a_thid_promotion"):
        await approve_promotion(db, merge_log_id=merge_log.id,
                                facility_id=fid, approved_by=uuid.uuid4(),
                                state_code="RJ", facility_code="JPR001")


@pytest.mark.asyncio
async def test_approve_promotion_assigns_uhid_and_updates_identity_path():
    fid = uuid.uuid4()
    requester = uuid.uuid4()
    approver = uuid.uuid4()
    patient = _make_patient(facility_id=fid, uhid=None)
    merge_log = _make_merge_log(status="pending", requested_by=requester,
                                source_patient_id=patient.id)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=merge_log)
    ))
    db.get = AsyncMock(return_value=patient)

    capture = _FakeAuditCapture()
    with patch("app.emergency.service.audited_mutation",
               return_value=_FakeAuditedMutation(capture)), \
         patch("app.emergency.service.generate_uhid",
               new=AsyncMock(return_value="IN-RJ-JPR001-2026-000001-5")):
        await approve_promotion(db, merge_log_id=merge_log.id,
                                facility_id=fid, approved_by=approver,
                                state_code="RJ", facility_code="JPR001")

    assert patient.uhid == "IN-RJ-JPR001-2026-000001-5"
    assert patient.identity_path == "demographics_only"
    assert patient.updated_by == approver
    assert capture.old_value == {"uhid": None, "identity_path": "thid"}
    assert capture.new_value == {"uhid": "IN-RJ-JPR001-2026-000001-5",
                                 "identity_path": "demographics_only"}
    assert merge_log.status == "approved"
    assert merge_log.approved_by == approver


# ---------------------------------------------------------------------------
# unmerge_promotion()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unmerge_self_unmerge_blocked():
    approver = uuid.uuid4()
    fid = uuid.uuid4()
    patient = _make_patient(facility_id=fid, identity_path="demographics_only",
                            uhid="IN-RJ-JPR001-2026-000001-5")
    merge_log = _make_merge_log(status="approved", approved_by=approver,
                                source_patient_id=patient.id)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=merge_log)
    ))
    db.get = AsyncMock(return_value=patient)
    with pytest.raises(ValueError, match="self_unmerge_not_allowed"):
        await unmerge_promotion(db, merge_log_id=merge_log.id,
                                facility_id=fid, unmerged_by=approver,
                                unmerge_reason="test")


@pytest.mark.asyncio
async def test_unmerge_not_approved_status():
    fid = uuid.uuid4()
    merge_log = _make_merge_log(status="pending", approved_by=None)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=merge_log)
    ))
    with pytest.raises(ValueError, match="not_approved"):
        await unmerge_promotion(db, merge_log_id=merge_log.id,
                                facility_id=fid, unmerged_by=uuid.uuid4(),
                                unmerge_reason=None)


@pytest.mark.asyncio
async def test_unmerge_restores_thid_state():
    fid = uuid.uuid4()
    approver = uuid.uuid4()
    unmerger = uuid.uuid4()
    patient = _make_patient(facility_id=fid, identity_path="demographics_only",
                            uhid="IN-RJ-JPR001-2026-000001-5")
    merge_log = _make_merge_log(status="approved", approved_by=approver,
                                source_patient_id=patient.id)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=merge_log)
    ))
    db.get = AsyncMock(return_value=patient)

    capture = _FakeAuditCapture()
    with patch("app.emergency.service.audited_mutation",
               return_value=_FakeAuditedMutation(capture)):
        await unmerge_promotion(db, merge_log_id=merge_log.id,
                                facility_id=fid, unmerged_by=unmerger,
                                unmerge_reason="Patient identified, use existing UHID")

    assert patient.uhid is None
    assert patient.identity_path == "thid"
    assert patient.updated_by == unmerger
    assert merge_log.status == "unmerged"
    assert merge_log.unmerge_reason == "Patient identified, use existing UHID"
    assert capture.old_value == {"uhid": "IN-RJ-JPR001-2026-000001-5",
                                 "identity_path": "demographics_only"}
    assert capture.new_value == {"uhid": None, "identity_path": "thid"}

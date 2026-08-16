"""
Tests for B2 fixes — schema compliance audit 2026-08-13.

Covers:
  - approve_merge: audited_mutation(UHID_MERGE) + row_version increment
  - approve_promotion: row_version increment
  - unmerge_promotion: row_version increment
  - get_patient_history_endpoint: merged patient follow + deterministic role tier
  - _resolve_role_tier (inline priority logic in router)
  - GET /patients/{id}/abha: response shape, encrypted token never returned
  - GET /patients/{id}/consents: delegates to consent service, facility gate

All tests use mocks — no live Postgres needed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers shared across test groups
# ---------------------------------------------------------------------------

def _make_patient(**kwargs) -> MagicMock:
    p = MagicMock()
    p.id = kwargs.get("id", uuid.uuid4())
    p.facility_id = kwargs.get("facility_id", uuid.uuid4())
    p.status = kwargs.get("status", "active")
    p.deleted_at = kwargs.get("deleted_at", None)
    p.uhid = kwargs.get("uhid", "IN-TS-TST01-2026-000001-7")
    p.thid = kwargs.get("thid", None)
    p.identity_path = kwargs.get("identity_path", "demographics_only")
    p.merged_into_patient_id = kwargs.get("merged_into_patient_id", None)
    p.row_version = kwargs.get("row_version", 1)
    return p


def _make_merge_log(**kwargs) -> MagicMock:
    ml = MagicMock()
    ml.id = kwargs.get("id", uuid.uuid4())
    ml.status = kwargs.get("status", "pending")
    ml.source_type = kwargs.get("source_type", "duplicate_uhid")
    ml.source_patient_id = kwargs.get("source_patient_id", uuid.uuid4())
    ml.target_patient_id = kwargs.get("target_patient_id", uuid.uuid4())
    ml.requested_by = kwargs.get("requested_by", uuid.uuid4())
    ml.approved_by = kwargs.get("approved_by", None)
    ml.reason = kwargs.get("reason", "duplicate record")
    ml.after_snapshot = None
    return ml


class _FakeAuditCapture:
    resource_id = None
    old_value = None
    new_value = None
    reason = None


class _FakeAuditedMutation:
    def __init__(self, capture=None):
        self._capture = capture or _FakeAuditCapture()

    async def __aenter__(self):
        return self._capture

    async def __aexit__(self, *_):
        pass


# ---------------------------------------------------------------------------
# approve_merge — UHID_MERGE audit row + row_version increment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_merge_writes_uhid_merge_audit():
    """approve_merge must call audited_mutation(UHID_MERGE) — the merge
    action is permanent and must appear in the audit trail."""
    from app.patients.service import approve_merge, REPOINTED_ON_MERGE, PENDING_REPOINT_OTHER_MODULES, AUDIT_TABLES_EXEMPT_FROM_REPOINTING

    requester = uuid.uuid4()
    approver = uuid.uuid4()  # different person
    fid = uuid.uuid4()

    source = _make_patient(facility_id=fid, status="active")
    target = _make_patient(facility_id=fid, status="active")

    ml = _make_merge_log(
        status="pending",
        source_type="duplicate_uhid",
        source_patient_id=source.id,
        target_patient_id=target.id,
        requested_by=requester,
    )

    db = AsyncMock()
    # execute() returns the merge log (FOR UPDATE select), then source, target
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = ml
    db.execute = AsyncMock(return_value=execute_result)
    db.get = AsyncMock(side_effect=lambda model, pk: source if pk == ml.source_patient_id else target)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    capture = _FakeAuditCapture()

    with patch("app.patients.service.audited_mutation", return_value=_FakeAuditedMutation(capture)) as mock_am, \
         patch("app.patients.service._tables_with_fk_to_patients", return_value=REPOINTED_ON_MERGE | PENDING_REPOINT_OTHER_MODULES | AUDIT_TABLES_EXEMPT_FROM_REPOINTING), \
         patch("app.patients.service._repoint_identifiers", new_callable=AsyncMock), \
         patch("app.patients.service._repoint_visits", new_callable=AsyncMock), \
         patch("app.patients.service._repoint_ot_schedules", new_callable=AsyncMock):

        await approve_merge(db, merge_log_id=ml.id, approved_by=approver)

    # audited_mutation was called with UHID_MERGE action
    from app.audit.actions import AuditAction
    call_kwargs = mock_am.call_args.kwargs
    assert call_kwargs["action"] == AuditAction.UHID_MERGE
    assert call_kwargs["resource_type"] == "patients"


@pytest.mark.asyncio
async def test_approve_merge_increments_row_version():
    """source.row_version must be incremented inside approve_merge."""
    from app.patients.service import approve_merge, REPOINTED_ON_MERGE, PENDING_REPOINT_OTHER_MODULES, AUDIT_TABLES_EXEMPT_FROM_REPOINTING

    requester = uuid.uuid4()
    approver = uuid.uuid4()
    fid = uuid.uuid4()

    source = _make_patient(facility_id=fid, status="active", row_version=3)
    target = _make_patient(facility_id=fid, status="active")

    ml = _make_merge_log(
        status="pending",
        source_patient_id=source.id,
        target_patient_id=target.id,
        requested_by=requester,
    )

    db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = ml
    db.execute = AsyncMock(return_value=execute_result)
    db.get = AsyncMock(side_effect=lambda model, pk: source if pk == ml.source_patient_id else target)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    with patch("app.patients.service.audited_mutation", return_value=_FakeAuditedMutation()), \
         patch("app.patients.service._tables_with_fk_to_patients", return_value=REPOINTED_ON_MERGE | PENDING_REPOINT_OTHER_MODULES | AUDIT_TABLES_EXEMPT_FROM_REPOINTING), \
         patch("app.patients.service._repoint_identifiers", new_callable=AsyncMock), \
         patch("app.patients.service._repoint_visits", new_callable=AsyncMock), \
         patch("app.patients.service._repoint_ot_schedules", new_callable=AsyncMock):

        await approve_merge(db, merge_log_id=ml.id, approved_by=approver)

    assert source.row_version == 4  # was 3, must be 4


@pytest.mark.asyncio
async def test_approve_merge_self_approval_blocked():
    from app.patients.service import approve_merge

    same_user = uuid.uuid4()
    ml = _make_merge_log(status="pending", requested_by=same_user)

    db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = ml
    db.execute = AsyncMock(return_value=execute_result)

    with pytest.raises(ValueError, match="self_approval_not_allowed"):
        await approve_merge(db, merge_log_id=ml.id, approved_by=same_user)


# ---------------------------------------------------------------------------
# approve_promotion — row_version increment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_promotion_increments_row_version():
    """approve_promotion must increment patient.row_version inside the
    audited_mutation block."""
    from app.emergency.service import approve_promotion

    requester = uuid.uuid4()
    approver = uuid.uuid4()
    fid = uuid.uuid4()

    patient = _make_patient(
        facility_id=fid,
        status="active",
        identity_path="thid",
        uhid=None,
        row_version=1,
    )
    patient.uhid = None  # explicit: THID patient has no UHID yet

    ml = _make_merge_log(
        status="pending",
        source_type="thid",
        source_patient_id=patient.id,
        target_patient_id=patient.id,
        requested_by=requester,
        approved_by=None,
    )

    db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = ml
    db.execute = AsyncMock(return_value=execute_result)
    db.get = AsyncMock(return_value=patient)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    with patch("app.emergency.service.audited_mutation", return_value=_FakeAuditedMutation()), \
         patch("app.emergency.service.generate_uhid", new_callable=AsyncMock, return_value="IN-TS-TST01-2026-000042-7"):

        await approve_promotion(
            db,
            merge_log_id=ml.id,
            facility_id=fid,
            approved_by=approver,
            state_code="TS",
            facility_code="TST01",
            facility_timezone="Asia/Kolkata",
        )

    assert patient.row_version == 2


# ---------------------------------------------------------------------------
# unmerge_promotion — row_version increment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unmerge_promotion_increments_row_version():
    """unmerge_promotion must increment patient.row_version."""
    from app.emergency.service import unmerge_promotion

    approver = uuid.uuid4()
    unmerger = uuid.uuid4()  # different from approver
    fid = uuid.uuid4()

    patient = _make_patient(
        facility_id=fid,
        status="active",
        identity_path="demographics_only",
        uhid="IN-TS-TST01-2026-000042-7",
        row_version=2,
    )

    ml = _make_merge_log(
        status="approved",
        source_type="thid",
        source_patient_id=patient.id,
        target_patient_id=patient.id,
        approved_by=approver,
    )

    db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = ml
    db.execute = AsyncMock(return_value=execute_result)
    db.get = AsyncMock(return_value=patient)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    with patch("app.emergency.service.audited_mutation", return_value=_FakeAuditedMutation()):
        await unmerge_promotion(
            db,
            merge_log_id=ml.id,
            facility_id=fid,
            unmerged_by=unmerger,
            unmerge_reason="test unmerge",
        )

    assert patient.row_version == 3


@pytest.mark.asyncio
async def test_unmerge_promotion_self_unmerge_blocked():
    """The supervisor who approved cannot also unmerge (maker-checker)."""
    from app.emergency.service import unmerge_promotion

    approver = uuid.uuid4()
    fid = uuid.uuid4()
    patient = _make_patient(facility_id=fid)

    ml = _make_merge_log(
        status="approved",
        source_type="thid",
        source_patient_id=patient.id,
        target_patient_id=patient.id,
        approved_by=approver,
    )

    db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = ml
    db.execute = AsyncMock(return_value=execute_result)
    db.get = AsyncMock(return_value=patient)

    with pytest.raises(ValueError, match="self_unmerge_not_allowed"):
        await unmerge_promotion(
            db,
            merge_log_id=ml.id,
            facility_id=fid,
            unmerged_by=approver,  # same as approved_by — must be blocked
            unmerge_reason="trying to self-unmerge",
        )


# ---------------------------------------------------------------------------
# Role tier resolution — deterministic priority
# ---------------------------------------------------------------------------

def _resolve_role_tier(user_roles: list[str]) -> str:
    """Mirror of the inline logic in patients/router.py."""
    _ROLE_PRIORITY = ["doctor", "nurse", "receptionist", "admin"]
    role_set = set(user_roles)
    return next((r for r in _ROLE_PRIORITY if r in role_set), "receptionist")


def test_role_tier_doctor_wins_over_nurse():
    assert _resolve_role_tier(["nurse", "doctor"]) == "doctor"


def test_role_tier_nurse_wins_over_receptionist():
    assert _resolve_role_tier(["receptionist", "nurse"]) == "nurse"


def test_role_tier_single_role():
    assert _resolve_role_tier(["admin"]) == "admin"


def test_role_tier_unknown_role_defaults_to_receptionist():
    assert _resolve_role_tier(["auditor"]) == "receptionist"


def test_role_tier_empty_defaults_to_receptionist():
    assert _resolve_role_tier([]) == "receptionist"


def test_role_tier_doctor_wins_over_admin():
    assert _resolve_role_tier(["admin", "doctor"]) == "doctor"


# ---------------------------------------------------------------------------
# History endpoint — merged patient follow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_follows_merged_patient_to_canonical():
    """When the requested patient is merged, history must be fetched for
    the canonical (target) patient, not the tombstone."""
    from app.patients.router import get_patient_history_endpoint

    fid = uuid.uuid4()
    merged_patient_id = uuid.uuid4()
    canonical_patient_id = uuid.uuid4()

    merged_patient = _make_patient(
        id=merged_patient_id,
        facility_id=fid,
        status="merged",
        merged_into_patient_id=canonical_patient_id,
    )
    canonical_patient = _make_patient(
        id=canonical_patient_id,
        facility_id=fid,
        status="active",
    )

    db = AsyncMock()
    db.get = AsyncMock(side_effect=lambda model, pk: (
        merged_patient if pk == merged_patient_id else canonical_patient
    ))

    user = MagicMock()
    user.facility_id = fid
    user.roles = ["doctor"]

    fake_history = {"visits": [], "encounters": []}

    with patch("app.patients.router.get_patient_history", new_callable=AsyncMock, return_value=fake_history) as mock_history:
        result = await get_patient_history_endpoint(
            patient_id=merged_patient_id,
            current_db_user=user,
            db=db,
        )

    # History was fetched for canonical, not the tombstone
    call_kwargs = mock_history.call_args.kwargs
    assert call_kwargs["patient_id"] == canonical_patient_id

    # Response includes merged_from_patient_id
    assert result["merged_from_patient_id"] == str(merged_patient_id)


@pytest.mark.asyncio
async def test_history_active_patient_no_merged_from():
    """A non-merged patient must not have merged_from_patient_id in response."""
    from app.patients.router import get_patient_history_endpoint

    fid = uuid.uuid4()
    pid = uuid.uuid4()
    patient = _make_patient(id=pid, facility_id=fid, status="active")

    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)

    user = MagicMock()
    user.facility_id = fid
    user.roles = ["nurse"]

    fake_history = {"visits": []}

    with patch("app.patients.router.get_patient_history", new_callable=AsyncMock, return_value=fake_history):
        result = await get_patient_history_endpoint(
            patient_id=pid,
            current_db_user=user,
            db=db,
        )

    assert "merged_from_patient_id" not in result


# ---------------------------------------------------------------------------
# GET /patients/{id}/abha — response shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_abha_endpoint_returns_correct_fields():
    """abha_number and abha_linked_at returned; encrypted token never returned."""
    from app.patients.router import get_patient_abha

    fid = uuid.uuid4()
    pid = uuid.uuid4()
    patient = _make_patient(id=pid, facility_id=fid)
    patient.abha_number = "12-3456-7890-1234"
    patient.abha_linked_at = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
    patient.abha_linking_key_version = 1
    patient.abha_linking_token_encrypted = b"should-never-appear-in-response"

    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)

    user = MagicMock()
    user.facility_id = fid

    result = await get_patient_abha(patient_id=pid, current_db_user=user, db=db)

    assert result["patient_id"] == str(pid)
    assert result["abha_number"] == "12-3456-7890-1234"
    assert result["abha_linked_at"] == "2026-07-01T10:00:00+00:00"
    assert result["abha_linking_key_version"] == 1
    # Encrypted token must never be in the response
    assert "abha_linking_token_encrypted" not in result


@pytest.mark.asyncio
async def test_abha_endpoint_wrong_facility_raises_404():
    from fastapi import HTTPException
    from app.patients.router import get_patient_abha

    fid = uuid.uuid4()
    patient = _make_patient(facility_id=fid)

    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)

    user = MagicMock()
    user.facility_id = uuid.uuid4()  # different facility

    with pytest.raises(HTTPException) as exc:
        await get_patient_abha(patient_id=patient.id, current_db_user=user, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_abha_endpoint_null_linked_at():
    """abha_linked_at=None when not linked yet."""
    from app.patients.router import get_patient_abha

    fid = uuid.uuid4()
    pid = uuid.uuid4()
    patient = _make_patient(id=pid, facility_id=fid)
    patient.abha_number = None
    patient.abha_linked_at = None
    patient.abha_linking_key_version = None
    patient.abha_linking_token_encrypted = None

    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)

    user = MagicMock()
    user.facility_id = fid

    result = await get_patient_abha(patient_id=pid, current_db_user=user, db=db)
    assert result["abha_linked_at"] is None
    assert result["abha_number"] is None


# ---------------------------------------------------------------------------
# GET /patients/{id}/consents — delegates to consent service
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consents_endpoint_delegates_to_service():
    """Consent list endpoint must call list_consent_records_for_patient
    with the correct patient_id and facility_id."""
    from app.patients.router import get_patient_consents

    fid = uuid.uuid4()
    pid = uuid.uuid4()
    patient = _make_patient(id=pid, facility_id=fid)

    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)

    user = MagicMock()
    user.facility_id = fid

    fake_records = []

    with patch("app.patients.router._consent_service.list_consent_records_for_patient",
               new_callable=AsyncMock, return_value=fake_records) as mock_svc:
        result = await get_patient_consents(
            patient_id=pid, current_db_user=user, db=db
        )

    mock_svc.assert_awaited_once_with(db, pid, facility_id=fid)
    assert result == []


@pytest.mark.asyncio
async def test_consents_endpoint_wrong_facility_raises_404():
    from fastapi import HTTPException
    from app.patients.router import get_patient_consents

    fid = uuid.uuid4()
    patient = _make_patient(facility_id=fid)

    db = AsyncMock()
    db.get = AsyncMock(return_value=patient)

    user = MagicMock()
    user.facility_id = uuid.uuid4()  # different facility

    with pytest.raises(HTTPException) as exc:
        await get_patient_consents(patient_id=patient.id, current_db_user=user, db=db)
    assert exc.value.status_code == 404

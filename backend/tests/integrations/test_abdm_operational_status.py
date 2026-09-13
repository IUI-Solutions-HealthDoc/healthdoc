"""Readiness metadata must not upgrade a queued job or unrelated consent to permission."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts import abdm_operational_status as diagnostics

NOW = datetime(2026, 9, 12, 10, tzinfo=UTC)


def link(**changes):
    return SimpleNamespace(
        **{
            "status": "pending",
            "confirmed_at": None,
            "token_present": False,
            "token_use_until": None,
            "patient_id": uuid.uuid4(),
            "facility_id": uuid.uuid4(),
            **changes,
        }
    )


@pytest.mark.parametrize(
    "job_state,expected",
    [
        ("pending", "token_dispatch_pending"),
        ("leased", "token_dispatch_in_progress_or_lease_expired"),
        ("done", "token_callback_missing_dispatch_completion_is_not_acceptance"),
        ("dead", "token_dispatch_stopped_inspect_before_retry"),
    ],
)
def test_job_completion_does_not_mean_callback_or_confirmation(job_state, expected):
    assert diagnostics.link_stage(link(), SimpleNamespace(status=job_state), now=NOW) == expected


def test_token_presence_does_not_mean_link_confirmation_or_extend_expiry():
    row = link(token_present=True, token_use_until=NOW + timedelta(minutes=1))
    assert diagnostics.link_stage(row, None, now=NOW) == "token_received_link_confirmation_pending"
    row.token_use_until = NOW
    assert diagnostics.link_stage(row, None, now=NOW) == "token_use_window_expired"
    row.status = "confirmed"
    assert diagnostics.link_stage(row, None, now=NOW) == "inconsistent_confirmation"
    row.confirmed_at = NOW
    assert diagnostics.link_stage(row, None, now=NOW) == "confirmed"


def test_consent_metadata_is_patient_and_purpose_specific_without_granting_access():
    row = link()
    consent = SimpleNamespace(
        patient_id=row.patient_id,
        status="granted",
        purpose_code="clinical_review",
        granted_at=NOW - timedelta(hours=1),
        expires_at=None,
    )
    result = diagnostics.consent_metadata(consent, row, now=NOW)
    assert result["active_at_check"]  # Null expiry is supported by the existing consent policy.
    assert result["matches_selected_patient"] and result["clinical_review_purpose"]
    assert not result["authorizes_transmission"] and not result["scope_and_phr_approval_checked"]
    consent.patient_id = uuid.uuid4()
    consent.purpose_code = "research"
    result = diagnostics.consent_metadata(consent, row, now=NOW)
    assert not result["matches_selected_patient"] and not result["clinical_review_purpose"]
    consent.expires_at = NOW
    assert not diagnostics.consent_metadata(consent, row, now=NOW)["active_at_check"]
    consent.expires_at = None
    consent.granted_at = NOW + timedelta(hours=1)
    assert not diagnostics.consent_metadata(consent, row, now=NOW)["active_at_check"]
    consent.granted_at = NOW
    consent.status = "revoked"
    assert not diagnostics.consent_metadata(consent, row, now=NOW)["active_at_check"]


@pytest.mark.parametrize("problem", ["none", "blank", "uri", "inactive", "facility", "missing"])
def test_requester_uses_real_validation_without_disclosing_identity(problem):
    row = link()
    staff = SimpleNamespace(
        is_active=True,
        facility_id=row.facility_id,
        full_name="Synthetic Private Name",
        registration_number="TEST-PRIVATE",
        registration_identifier_type="REGNO1",
        registration_identifier_system="https://registry.test",
    )
    if problem == "blank":
        staff.registration_number = " "
    elif problem == "uri":
        staff.registration_identifier_system = "https://user:secret@registry.test"
    elif problem == "inactive":
        staff.is_active = False
    elif problem == "facility":
        staff.facility_id = uuid.uuid4()
    elif problem == "missing":
        staff = None
    result = diagnostics.requester_metadata(staff, row)
    assert result["profile_complete_for_selected_facility"] is (problem == "none")
    assert not result["registry_membership_verified"]
    assert all(
        value not in json.dumps(result) for value in ["Private Name", "TEST-PRIVATE", "secret"]
    )


def test_missing_inputs_never_report_ready():
    assert diagnostics.link_stage(None, None, now=NOW) == "not_selected_or_missing"
    assert not any(diagnostics.consent_metadata(None, None, now=NOW).values())
    assert not any(diagnostics.requester_metadata(None, None).values())


async def test_status_transaction_is_read_only_and_never_commits(monkeypatch, capsys):
    db = AsyncMock()
    grouped = MagicMock()
    grouped.all.return_value = []
    staff = MagicMock()
    staff.one_or_none.return_value = None
    db.execute.side_effect = [None, grouped, staff]
    db.scalar.return_value = 0
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=db)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(diagnostics, "SessionLocal", factory)
    result = await diagnostics.status()
    assert str(db.execute.call_args_list[0].args[0]) == "SET TRANSACTION READ ONLY"
    db.commit.assert_not_called()
    assert not result["live_exchange_verified"]
    assert json.loads(capsys.readouterr().out)["stored_link_tokens"] == 0


async def test_selected_snapshot_correlates_job_and_never_prints_patient_or_staff(
    monkeypatch, capsys
):
    row = link(token_request_id=str(uuid.uuid4()))
    consent = SimpleNamespace(
        patient_id=uuid.uuid4(),
        status="granted",
        purpose_code="research",
        granted_at=NOW,
        expires_at=None,
    )
    staff = SimpleNamespace(
        is_active=True,
        facility_id=row.facility_id,
        full_name="DO-NOT-PRINT-NAME",
        registration_number="DO-NOT-PRINT-REGISTRATION",
        registration_identifier_type="REGNO1",
        registration_identifier_system="https://registry.test",
    )
    job = SimpleNamespace(status="done", _mapping={"status": "done", "attempts": 1})
    grouped = MagicMock()
    grouped.all.return_value = []
    responses = [None, grouped]
    for value in [row, job, consent, staff]:
        response = MagicMock()
        response.one_or_none.return_value = value
        responses.append(response)
    db = AsyncMock()
    db.execute.side_effect = responses
    db.scalar.return_value = 0
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=db)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(diagnostics, "SessionLocal", factory)
    ident = uuid.uuid4()
    result = await diagnostics.status(ident, uuid.uuid4(), "chosen.staff")
    assert "callback_missing" in result["selected_link"]["stage"]
    assert not result["local_consent"]["matches_selected_patient"]
    assert result["requester"]["profile_complete_for_selected_facility"]
    encoded = capsys.readouterr().out
    for forbidden in [
        str(row.patient_id),
        str(consent.patient_id),
        str(row.facility_id),
        staff.full_name,
        staff.registration_number,
        staff.registration_identifier_system,
    ]:
        assert forbidden not in encoded
    query = db.execute.call_args_list[3].args[0].compile()
    assert set(query.params.values()) == {
        diagnostics.job_id("link_token", ident),
        ident,
        "link_token",
        row.facility_id,
    }
    assert "chosen.staff" in db.execute.call_args_list[-1].args[0].compile().params.values()
    assert str(db.execute.call_args_list[0].args[0]) == "SET TRANSACTION READ ONLY"
    db.commit.assert_not_called()

"""No sample clinician or inferred issuing authority on an M3 consent ask."""

import copy
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.integrations.abdm.hiu.requester import RequesterUnavailable, from_staff, validate_requester
from app.users.router import _validate_requester_fields
from app.users.schemas import UserUpdate

IDENTITY = {
    "name": "Synthetic Test Clinician",
    "identifier": {"type": "REGNO1", "value": "TEST-ONLY", "system": "https://registry.test"},
}


@pytest.mark.parametrize("field", ["name", "type", "value", "system"])
@pytest.mark.parametrize("invalid", [None, "", " ", "change-me", 123])
def test_requester_rejects_incomplete_identity_without_inventing_defaults(field, invalid):
    body = copy.deepcopy(IDENTITY)
    (body if field == "name" else body["identifier"])[field] = invalid
    with pytest.raises(RequesterUnavailable):
        validate_requester(body)


@pytest.mark.parametrize(
    "uri",
    [
        "registry.test",
        "javascript:alert(1)",
        "https://user:secret@registry.test",
        "https://registry.test?secret=value",
        "https://registry.test#value",
        "https://bad host.test",
    ],
)
def test_requester_registry_uri_is_explicit_and_contains_no_credentials(uri):
    body = copy.deepcopy(IDENTITY)
    body["identifier"]["system"] = uri
    with pytest.raises(RequesterUnavailable) as error:
        validate_requester(body)
    assert "secret" not in str(error.value)


def test_requester_is_a_snapshot_not_a_reference_to_the_input():
    body = copy.deepcopy(IDENTITY)
    snapshot = validate_requester(body)
    body["identifier"]["value"] = "CHANGED"
    assert snapshot == IDENTITY


@pytest.mark.parametrize("problem", ["missing", "inactive", "facility"])
def test_requester_must_be_an_active_staff_member_of_the_requesting_facility(problem):
    facility = uuid.uuid4()
    staff = SimpleNamespace(is_active=True, facility_id=facility)
    if problem == "missing":
        staff = None
    elif problem == "inactive":
        staff.is_active = False
    else:
        staff.facility_id = uuid.uuid4()
    with pytest.raises(RequesterUnavailable):
        from_staff(staff, facility)


def test_admin_must_supply_registration_metadata_together_but_can_clear_it():
    existing = SimpleNamespace(
        full_name=IDENTITY["name"],
        registration_number="TEST-ONLY",
        registration_identifier_type="REGNO1",
        registration_identifier_system="https://registry.test",
    )
    _validate_requester_fields(UserUpdate(full_name="Updated Test Name"), existing)
    with pytest.raises(HTTPException) as error:
        _validate_requester_fields(UserUpdate(registration_number=None), existing)
    assert error.value.status_code == 422
    _validate_requester_fields(
        UserUpdate(
            registration_identifier_type=None,
            registration_identifier_system=None,
        ),
        existing,
    )


SANDBOX_USER = uuid.uuid4()


@pytest.fixture
def sandbox(monkeypatch):
    from app.common.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "dev")
    monkeypatch.setattr(settings, "abdm_gateway_base_url", "https://dev.abdm.gov.in")
    monkeypatch.setattr(settings, "abdm_x_cm_id", "sbx")
    monkeypatch.setattr(settings, "abdm_sandbox_test_requester_user_ids", (SANDBOX_USER,))
    facility = uuid.uuid4()
    staff = SimpleNamespace(
        id=SANDBOX_USER, username="dev.doctor", full_name="Dev Doctor", is_active=True,
        facility_id=facility, registration_number=None, registration_identifier_type=None,
        registration_identifier_system=None,
    )
    return settings, staff, facility


def test_allowlisted_dev_account_asks_as_nha_sample_requester(sandbox):
    from app.integrations.abdm.hiu.requester import SANDBOX_TEST_REQUESTER

    _, staff, facility = sandbox
    assert from_staff(staff, facility) == SANDBOX_TEST_REQUESTER
    # The sample's registry URI is not a real host and the name says "test".
    assert SANDBOX_TEST_REQUESTER["identifier"] == {
        "type": "REGNO1", "value": "MH1001", "system": "https://www.mciindia.9985",
    }
    assert "SANDBOX TEST" in SANDBOX_TEST_REQUESTER["name"]


def test_allowlist_wins_over_a_filled_dev_profile_so_snapshots_agree(sandbox):
    from app.integrations.abdm.hiu.requester import SANDBOX_TEST_REQUESTER

    _, staff, facility = sandbox
    staff.registration_number = "TEST-ONLY"
    staff.registration_identifier_type = "REGNO1"
    staff.registration_identifier_system = "https://registry.test"
    assert from_staff(staff, facility) == SANDBOX_TEST_REQUESTER


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("environment", "production"),
        ("abdm_gateway_base_url", "https://live.abdm.gov.in"),
        ("abdm_gateway_base_url", "https://dev.abdm.gov.in.evil.example"),
        ("abdm_gateway_base_url", "http://dev.abdm.gov.in"),
        ("abdm_x_cm_id", "abdm"),
        ("abdm_sandbox_test_requester_user_ids", ()),
    ],
)
def test_sandbox_requester_never_applies_outside_the_nha_sandbox(sandbox, monkeypatch, field, value):
    settings, staff, facility = sandbox
    monkeypatch.setattr(settings, field, value)
    with pytest.raises(RequesterUnavailable):
        from_staff(staff, facility)


@pytest.mark.parametrize("change", ["username", "inactive", "facility", "other_account"])
def test_sandbox_requester_needs_the_exact_active_dev_account(sandbox, change):
    _, staff, facility = sandbox
    if change == "username":
        staff.username = "dr.real"
    elif change == "inactive":
        staff.is_active = False
    elif change == "facility":
        staff.facility_id = uuid.uuid4()
    else:
        staff.id = uuid.uuid4()
    with pytest.raises(RequesterUnavailable):
        from_staff(staff, facility)


def test_sandbox_requester_allowlist_defaults_closed():
    from app.common.config import Settings

    assert Settings.model_construct().abdm_sandbox_test_requester_user_ids == ()

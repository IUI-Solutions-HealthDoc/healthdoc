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

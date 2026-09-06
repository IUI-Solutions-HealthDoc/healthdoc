"""Regression guards for the authenticated development identity seed."""
import re
import uuid
from pathlib import Path

import pytest

from scripts.seed_dev_data import (
    DEPARTMENT_ID,
    DISPLAY_NAMES,
    UPDATE_USER,
    UPSERT_USER,
    _assert_exact_bind_parameters,
    _user_parameters,
)


@pytest.mark.parametrize("statement", [UPDATE_USER, UPSERT_USER])
def test_user_seed_statements_and_parameters_have_identical_bind_keys(statement):
    parameters = _user_parameters(
        "dev.hod", "keycloak-hod-subject", uuid.uuid4(), DEPARTMENT_ID
    )

    _assert_exact_bind_parameters(statement, parameters)
    assert set(statement._bindparams) == set(parameters)
    assert parameters["department_id"] == DEPARTMENT_ID


def test_bind_guard_reports_a_missing_parameter_at_the_call_site():
    parameters = _user_parameters(
        "dev.hod", "keycloak-hod-subject", uuid.uuid4(), DEPARTMENT_ID
    )
    parameters.pop("department_id")

    with pytest.raises(ValueError, match="missing=\\['department_id'\\]"):
        _assert_exact_bind_parameters(UPSERT_USER, parameters)


#: The shell array dev_setup.sh checks every account against before it prints a
#: success banner. Read rather than restated, because a hardcoded copy here is
#: a third list to keep in step and the first one anybody forgets.
_DEV_SETUP = Path(__file__).resolve().parents[2] / "scripts/dev_setup.sh"


def _advertised_logins() -> set[str]:
    block = re.search(r"DEV_USERNAMES=\(([^)]*)\)", _DEV_SETUP.read_text())
    assert block, f"DEV_USERNAMES array not found in {_DEV_SETUP}"
    names = set(re.findall(r"dev\.[a-z0-9]+", block.group(1)))
    # A regex that silently matches nothing would make the comparison below
    # pass for the wrong reason.
    assert len(names) >= 13, f"parsed only {len(names)} logins from DEV_USERNAMES"
    return names


def test_all_advertised_development_logins_have_seed_profiles():
    """Every login the setup script insists on must have a seed profile.

    dev_setup.sh refuses to print its success banner unless each name in
    DEV_USERNAMES exists in Keycloak; seed_dev_data then needs a display name
    for each. Adding an account to one and not the other used to leave a user
    who could log in and had no row in `users` — which presents as a broken
    application, not a broken seed.
    """
    assert set(DISPLAY_NAMES) == _advertised_logins()

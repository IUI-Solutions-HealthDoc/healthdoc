"""Regression guards for the authenticated development identity seed."""
import uuid

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


def test_all_advertised_development_logins_have_seed_profiles():
    assert set(DISPLAY_NAMES) == {
        "dev.receptionist", "dev.doctor", "dev.nurse", "dev.labtech",
        "dev.radiology", "dev.pharmacist", "dev.admin", "dev.auditor",
        "dev.patient", "dev.hod", "dev.emergency", "dev.supervisor",
        "dev.superadmin",
    }

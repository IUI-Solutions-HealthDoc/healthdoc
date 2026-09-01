"""Authorization boundary for the five HOD dashboard reads."""
import uuid

import pytest
from fastapi import HTTPException

from app.auth.deps import DbUser
from app.queue.router import (
    _require_hod_dashboard_department,
    _require_roster_list_department,
)


def _caller(*, roles: list[str], department_id: uuid.UUID | None) -> DbUser:
    return DbUser(
        id=uuid.uuid4(),
        keycloak_sub="hod-scope-test",
        username="hod.scope",
        facility_id=uuid.uuid4(),
        department_id=department_id,
        roles=roles,
    )


def test_hod_can_read_own_department():
    department_id = uuid.uuid4()

    _require_hod_dashboard_department(
        _caller(roles=["hod"], department_id=department_id), department_id
    )


def test_hod_cannot_read_another_department_in_the_same_facility():
    with pytest.raises(HTTPException) as exc:
        _require_hod_dashboard_department(
            _caller(roles=["hod"], department_id=uuid.uuid4()), uuid.uuid4()
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "hod_department_scope_violation"


def test_hod_without_a_department_fails_closed():
    with pytest.raises(HTTPException) as exc:
        _require_hod_dashboard_department(
            _caller(roles=["hod"], department_id=None), uuid.uuid4()
        )

    assert exc.value.status_code == 403


def test_admin_remains_facility_wide():
    _require_hod_dashboard_department(
        _caller(roles=["admin"], department_id=None), uuid.uuid4()
    )


def test_hod_only_roster_read_stays_in_own_department():
    with pytest.raises(HTTPException) as exc:
        _require_roster_list_department(
            _caller(roles=["hod"], department_id=uuid.uuid4()), uuid.uuid4()
        )

    assert exc.value.status_code == 403


@pytest.mark.parametrize("additional_role", ["doctor", "nurse", "receptionist", "admin"])
def test_hod_keeps_cross_department_roster_read_granted_by_another_role(additional_role):
    _require_roster_list_department(
        _caller(roles=["hod", additional_role], department_id=uuid.uuid4()),
        uuid.uuid4(),
    )

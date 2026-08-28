"""Identity input must be rejected before Keycloak or a facility database write."""

import pytest
from pydantic import ValidationError

from app.users.schemas import AccountRequestCreate, UserCreate


def test_usernames_cannot_contain_spaces() -> None:
    with pytest.raises(ValidationError):
        UserCreate(
            username="nurse one",
            full_name="Nurse One",
            roles=["nurse"],
            temporary_password="temporary-1",
        )


@pytest.mark.parametrize("role", ["patient", "superadmin"])
def test_facility_admin_cannot_mint_non_staff_roles(role: str) -> None:
    with pytest.raises(ValidationError):
        UserCreate(
            username="valid.user",
            full_name="Valid User",
            roles=[role],
            temporary_password="temporary-1",
        )


def test_multiple_facility_roles_remain_supported() -> None:
    user = UserCreate(
        username="doctor.hod",
        full_name="Doctor HOD",
        roles=["doctor", "hod"],
        temporary_password="temporary-1",
    )
    assert user.roles == ["doctor", "hod"]


def test_account_request_uses_the_same_identity_policy() -> None:
    with pytest.raises(ValidationError):
        AccountRequestCreate(
            requested_for_full_name="Platform Owner",
            requested_username="platform owner",
            requested_roles=["superadmin"],
            justification="Facility staffing must not create this role.",
        )

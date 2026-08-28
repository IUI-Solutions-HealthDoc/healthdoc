import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


StaffUsername = Annotated[
    str,
    Field(
        min_length=3,
        max_length=100,
        pattern=r"^[A-Za-z0-9._-]+$",
        description="Keycloak login id; spaces are not valid.",
    ),
]
FacilityStaffRole = Literal[
    "receptionist",
    "doctor",
    "nurse",
    "lab_tech",
    "radiology_tech",
    "pharmacist",
    "emergency",
    "supervisor",
    "admin",
    "hod",
    "auditor",
]


class UserCreate(BaseModel):
    username: StaffUsername
    full_name: str = Field(min_length=1)
    email: EmailStr | None = None
    mobile: str | None = Field(default=None, pattern=r"^\+91\d{10}$")
    designation: str | None = None
    employee_id: str | None = None
    registration_number: str | None = None
    qualification: str | None = None
    department_id: uuid.UUID | None = None
    #: Ignored — the account is created at the authenticated admin's facility.
    #: Optional rather than removed so existing callers keep validating; the
    #: router refuses a value that disagrees with the caller's own facility.
    facility_id: uuid.UUID | None = None
    roles: list[FacilityStaffRole] = Field(
        min_length=1,
        description="One or more facility staff roles. Patient and platform-superadmin use separate flows.",
    )
    temporary_password: str = Field(min_length=8)


class UserUpdate(BaseModel):
    full_name: Annotated[str, Field(min_length=1)] | None = None
    email: EmailStr | None = None
    mobile: str | None = Field(default=None, pattern=r"^\+91\d{10}$")
    designation: str | None = None
    employee_id: str | None = None
    registration_number: str | None = None
    qualification: str | None = None
    department_id: uuid.UUID | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    keycloak_sub: str
    username: str
    full_name: str
    email: str | None
    mobile: str | None
    designation: str | None
    employee_id: str | None
    registration_number: str | None
    qualification: str | None
    facility_id: uuid.UUID
    department_id: uuid.UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- 0028 maker-checker

class AccountRequestCreate(BaseModel):
    """Ask for a staff account. Creates nothing until an approver acts."""

    requested_for_full_name: str = Field(min_length=1)
    requested_username: StaffUsername
    requested_roles: list[FacilityStaffRole] = Field(
        min_length=1,
        description="One or more facility staff roles. Patient and platform-superadmin use separate flows.",
    )
    designation: str | None = None
    employee_id: str | None = None
    registration_number: str | None = None
    qualification: str | None = None
    email: EmailStr | None = None
    mobile: str | None = Field(default=None, pattern=r"^\+91\d{10}$")
    justification: str = Field(
        min_length=10,
        description="Why this account is needed. Required, and required to say "
                    "something — an approver cannot exercise judgement on a blank.",
    )
    #: No facility_id. The request is raised at the requester's own facility,
    #: from the token — same rule as UserCreate.


class AccountRequestApprove(BaseModel):
    temporary_password: str = Field(min_length=8)


class AccountRequestReject(BaseModel):
    reason: str = Field(
        min_length=1,
        description="Recorded on the request. A refusal with no reason is not "
                    "reviewable afterwards.",
    )


class AccountRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    facility_id: uuid.UUID
    requested_for_full_name: str
    requested_username: str
    requested_roles: list[str]
    designation: str | None
    employee_id: str | None
    registration_number: str | None
    qualification: str | None
    email: str | None
    mobile: str | None
    justification: str
    requested_by: uuid.UUID
    status: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    rejection_reason: str | None
    #: Set on approval — the users.id that was created. Null otherwise.
    created_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class AccountRequestListOut(BaseModel):
    items: list[AccountRequestOut]
    page: int
    page_size: int

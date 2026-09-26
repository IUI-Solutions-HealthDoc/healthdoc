"""GET /users/me — the caller's own identity and facility.

Why this exists
---------------
The frontend had no way to learn which facility it was operating in. There is
no session claim for it and no endpoint returned it, so five feature modules
worked around the gap with a hardcoded constant:

    export const FACILITY_ID = MOCK_FACILITY_ID;   // billing, admin, consent,
                                                   // audit-viewer, reports

That constant was not only fake, it was being *sent* — `CreateUserModal` and
`CreateAccountRequestModal` put it in the request body as `facility_id`. Since
`POST /users` now refuses a body `facility_id` that disagrees with the caller's
own facility (403), those screens would have failed on every submission the
moment they were wired to the real API.

The fix is not to give the browser a better constant. It is to stop the browser
asserting its facility at all: writes send nothing and the server derives scope
from the token, while this endpoint supplies the value for *display* only.

Why it is a separate router
---------------------------
`app/users/router.py` carries `dependencies=[Depends(require_roles("admin"))]`
on the APIRouter itself, because every other /users route is administrative.
`/me` must be readable by every authenticated role, so it cannot live there.

Route ordering matters and is not incidental: the admin router declares
`GET /users/{user_id}`. Registered first, that pattern captures `/users/me` and
fails 422 trying to parse "me" as a UUID. main.py therefore includes this
module *before* the MODULES loop. Moving it later will break the endpoint in a
way that looks like a validation bug rather than a routing one.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser
from app.common.db import get_db
from app.departments.models import Department
from app.users.models import Facility, User

router = APIRouter(prefix="/users", tags=["users"])


class FacilityOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    code: str
    name: str
    name_hi: str | None = None
    timezone: str


class DepartmentOut(BaseModel):
    """The caller's home department, or null.

    Null for facility-wide roles — admin and auditor belong to no one
    department — and for any staff member whose row predates the column.
    Callers must handle null rather than assume a department exists.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    code: str
    name: str
    name_hi: str | None = None


class MeOut(BaseModel):
    """Deliberately narrow.

    No email, mobile, employee_id or registration_number: this is read by every
    screen for every role, and a convenience endpoint is a poor place to widen
    what a compromised session can harvest about its own account. Anything more
    belongs on the admin-gated GET /users/{id}.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    username: str
    full_name: str
    roles: list[str]
    facility: FacilityOut
    #: Added for the HOD dashboard, which is per-department.
    #:
    #: Without this the screen would need a department picker, and a picker
    #: would be WRONG: the hod-dashboard endpoints are gated on the role and
    #: scoped only to the caller's FACILITY, so a picker would let the head of
    #: Medicine read Surgery's workload and pending approvals. The department a
    #: person belongs to is not theirs to choose.
    #:
    #: Still narrow per this class's own rule — id, code and name, which is what
    #: a screen needs to scope and label itself. Nothing about the department's
    #: staff or configuration.
    department: DepartmentOut | None


@router.get("/me", response_model=MeOut)
async def get_me(
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> MeOut:
    """The caller's own row and facility. No role gate — every authenticated
    role needs this, and it can only ever return the caller's own record."""
    row = (
        await db.execute(
            # OUTER join on departments: users.department_id is nullable, and an
            # inner join would make /users/me 404 for every admin and auditor —
            # turning "has no department" into "has no account".
            select(User, Facility, Department)
            .join(Facility, Facility.id == User.facility_id)
            .outerjoin(Department, Department.id == User.department_id)
            .where(User.id == current_db_user.id)
        )
    ).one_or_none()

    if row is None:
        # get_current_db_user already resolved this id from the token, so a miss
        # here means the row was deleted mid-session. 404 rather than 500: the
        # caller's own account genuinely no longer exists.
        raise HTTPException(status_code=404, detail="user_not_found")

    user, facility, department = row
    return MeOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        # From the token, not the users table: roles are Keycloak's to state,
        # and the app's copy can lag a realm change until the next login.
        roles=current_db_user.roles,
        facility=FacilityOut.model_validate(facility),
        department=DepartmentOut.model_validate(department) if department else None,
    )

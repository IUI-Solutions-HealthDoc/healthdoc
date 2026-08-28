"""users module — admin-managed staff accounts (Keycloak + Postgres profile).

FACILITY SCOPING (P0.4)
-----------------------
Every route here is scoped to the authenticated admin's facility, derived from
`CurrentDbUser` and never from a caller-supplied value.

Before this, the module was cross-tenant in five separate ways:

  * `list_users` took `facility_id` as an OPTIONAL query parameter — omitting it
    returned every staff account in every facility;
  * `get_user`, `update_user`, `activate_user` and `deactivate_user` performed no
    facility check at all, so any admin could read, rename, disable or re-enable
    any account in the deployment by id;
  * `create_user` read `facility_id` from the request body, so an admin could
    create a staff account inside somebody else's hospital — and, because
    Keycloak is created first, leave a real credential behind.

A user id from another facility now returns **404, not 403**. 403 confirms the
id exists, which turns this endpoint into an enumeration oracle for another
facility's staff list; 404 is indistinguishable from a nonexistent id.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.departments.models import Department
from app.users.models import User
from app.users.schemas import UserCreate, UserOut, UserUpdate
from app.users.service import KeycloakAdmin

router = APIRouter(prefix="/users", tags=["users"],
                   dependencies=[Depends(require_roles("admin"))])


async def _get_scoped_user(
    db: AsyncSession, user_id: uuid.UUID, caller_facility_id: uuid.UUID
) -> User:
    """One user, or 404 — including when it exists at another facility."""
    user = await db.get(User, user_id)
    if user is None or user.facility_id != caller_facility_id:
        raise HTTPException(404, "User not found")
    return user


async def _validate_department(
    db: AsyncSession,
    department_id: uuid.UUID | None,
    caller_facility_id: uuid.UUID,
) -> None:
    if department_id is None:
        return
    department = await db.get(Department, department_id)
    if (
        department is None
        or department.facility_id != caller_facility_id
        or not department.is_active
    ):
        raise HTTPException(
            422,
            {
                "code": "invalid_department",
                "message": "Select an active department in your facility.",
            },
        )


@router.get("")
async def list_users(
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    is_active: bool | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Staff at the caller's facility.

    The `facility_id` query parameter is gone rather than defaulted: an optional
    scope filter is one forgotten argument away from being no scope at all, and
    the argument was optional here.

    `search` matches username, full name or employee id. It is server-side on
    purpose: the admin screen offered a search box backed by a client-side
    filter over the *current page*, which silently hides matches on every other
    page — an admin searching for a staff member who is not on page one is told
    they do not exist.

    `total` is deliberately still absent from the response. Adding it means a
    second COUNT query on every page load, and nothing in the UI uses it; the
    frontend's Paginated<T> already types it optional.
    """
    q = select(User).where(User.facility_id == current_db_user.facility_id)
    if is_active is not None:
        q = q.where(User.is_active == is_active)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(
            or_(
                User.username.ilike(term),
                User.full_name.ilike(term),
                User.employee_id.ilike(term),
            )
        )
    q = q.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()
    return {"items": [UserOut.model_validate(r).model_dump(mode="json") for r in rows],
            "page": page, "page_size": page_size}


@router.get("/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await _get_scoped_user(db, user_id, current_db_user.facility_id)
    return UserOut.model_validate(user).model_dump(mode="json")


@router.post("", status_code=201)
async def create_user(
    payload: UserCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a staff account at the CALLER's facility.

    A body `facility_id` that disagrees is refused before Keycloak is touched.
    Order matters: Keycloak is the identity source of truth and is written
    first, so a rejection discovered afterwards would leave a usable credential
    for a facility the caller has no rights over.
    """
    if payload.facility_id is not None and payload.facility_id != current_db_user.facility_id:
        raise HTTPException(
            403,
            {
                "code": "facility_mismatch",
                "message": "facility_id must match the authenticated admin's facility",
            },
        )

    await _validate_department(db, payload.department_id, current_db_user.facility_id)

    existing = await db.execute(select(User).where(User.username == payload.username))
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Username '{payload.username}' already exists")

    # Keycloak first (source of truth for identity), then the profile row.
    sub = await KeycloakAdmin().create_user(
        username=payload.username, full_name=payload.full_name,
        email=payload.email, temporary_password=payload.temporary_password,
        roles=payload.roles,
    )
    user = User(
        keycloak_sub=sub,
        **payload.model_dump(exclude={"roles", "temporary_password", "facility_id"}),
        facility_id=current_db_user.facility_id,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return UserOut.model_validate(user).model_dump(mode="json")


@router.patch("/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await _get_scoped_user(db, user_id, current_db_user.facility_id)
    if "department_id" in payload.model_fields_set:
        await _validate_department(db, payload.department_id, current_db_user.facility_id)
    # facility_id is not updateable through this route even if the schema ever
    # gains it — moving a staff account between facilities is a transfer with
    # its own approval, not a field edit.
    for field, value in payload.model_dump(exclude_unset=True, exclude={"facility_id"}).items():
        setattr(user, field, value)
    await db.flush()
    await db.refresh(user)
    return UserOut.model_validate(user).model_dump(mode="json")


@router.post("/{user_id}/deactivate")
async def deactivate_user(
    user_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await _get_scoped_user(db, user_id, current_db_user.facility_id)
    await KeycloakAdmin().set_enabled(user.keycloak_sub, False)
    user.is_active = False
    await db.flush()
    return {"id": str(user.id), "is_active": False}


@router.post("/{user_id}/activate")
async def activate_user(
    user_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await _get_scoped_user(db, user_id, current_db_user.facility_id)
    await KeycloakAdmin().set_enabled(user.keycloak_sub, True)
    user.is_active = True
    await db.flush()
    return {"id": str(user.id), "is_active": True}

"""users module — admin-managed staff accounts (Keycloak + Postgres profile)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_roles
from app.common.db import get_db
from app.users.models import User
from app.users.schemas import UserCreate, UserOut, UserUpdate
from app.users.service import KeycloakAdmin

router = APIRouter(prefix="/users", tags=["users"],
                   dependencies=[Depends(require_roles("admin"))])


@router.get("")
async def list_users(
    db: AsyncSession = Depends(get_db),
    facility_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    q = select(User)
    if facility_id:
        q = q.where(User.facility_id == facility_id)
    if is_active is not None:
        q = q.where(User.is_active == is_active)
    q = q.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()
    return {"items": [UserOut.model_validate(r).model_dump(mode="json") for r in rows],
            "page": page, "page_size": page_size}


@router.get("/{user_id}")
async def get_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return UserOut.model_validate(user).model_dump(mode="json")


@router.post("", status_code=201)
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> dict:
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
        **payload.model_dump(exclude={"roles", "temporary_password"}),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return UserOut.model_validate(user).model_dump(mode="json")


@router.patch("/{user_id}")
async def update_user(user_id: uuid.UUID, payload: UserUpdate,
                      db: AsyncSession = Depends(get_db)) -> dict:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.flush()
    await db.refresh(user)
    return UserOut.model_validate(user).model_dump(mode="json")


@router.post("/{user_id}/deactivate")
async def deactivate_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    await KeycloakAdmin().set_enabled(user.keycloak_sub, False)
    user.is_active = False
    await db.flush()
    return {"id": str(user.id), "is_active": False}


@router.post("/{user_id}/activate")
async def activate_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    await KeycloakAdmin().set_enabled(user.keycloak_sub, True)
    user.is_active = True
    await db.flush()
    return {"id": str(user.id), "is_active": True}

"""departments module router — endpoints land here; see this module's GitHub issues."""
"""
CRUD for departments and rooms.
Mutations (create/update) are admin-only.
No delete endpoints — deactivation is PATCH is_active=false
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
 
from app.auth.deps import CurrentUser, require_roles
from app.common.db import get_db
from app.departments import service
from app.departments.schemas import (
    DepartmentCreate,
    DepartmentListOut,
    DepartmentOut,
    DepartmentUpdate,
    RoomCreate,
    RoomListOut,
    RoomOut,
    RoomUpdate,
)

router = APIRouter(prefix="/departments", tags=["departments"])


# ---------------- CREATE DEPARTMENT ----------------
@router.post("", status_code=201, dependencies=[Depends(require_roles("admin"))])
async def create_department(
    payload: DepartmentCreate, db: AsyncSession = Depends(get_db)
) -> dict:
    dept = await service.create_department(
        db, name=payload.name, code=payload.code, facility_id=payload.facility_id
    )
    return DepartmentOut.model_validate(dept).model_dump(mode="json")
 
 
# ---------------- LIST DEPARTMENTS ----------------
# Open to any authenticated user — needed for dropdowns across many modules.
@router.get("")
async def list_departments(
    user: CurrentUser,
    facility_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
) -> dict:
    items, total = await service.list_departments(
        db, facility_id=facility_id, is_active=is_active, page=page, page_size=page_size
    )
    return DepartmentListOut(
        items=[DepartmentOut.model_validate(d) for d in items],
        page=page,
        page_size=page_size,
        total=total,
    ).model_dump(mode="json")
 
 
# ---------------- CREATE ROOM ----------------
@router.post("/rooms", status_code=201, dependencies=[Depends(require_roles("admin"))])
async def create_room(payload: RoomCreate, db: AsyncSession = Depends(get_db)) -> dict:
    room = await service.create_room(
        db, department_id=payload.department_id, room_number=payload.room_number
    )
    return RoomOut.model_validate(room).model_dump(mode="json")
 
 
# ---------------- LIST ROOMS ----------------
@router.get("/rooms")
async def list_rooms(
    user: CurrentUser,
    department_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
) -> dict:
    items, total = await service.list_rooms(
        db, department_id=department_id, is_active=is_active, page=page, page_size=page_size
    )
    return RoomListOut(
        items=[RoomOut.model_validate(r) for r in items],
        page=page,
        page_size=page_size,
        total=total,
    ).model_dump(mode="json")
 
 
# ---------------- GET ROOM ----------------
@router.get("/rooms/{room_id}")
async def get_room(
    room_id: uuid.UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> dict:
    room = await service.get_room(db, room_id)
    return RoomOut.model_validate(room).model_dump(mode="json")
 
 
# ---------------- UPDATE ROOM ----------------
@router.patch("/rooms/{room_id}", dependencies=[Depends(require_roles("admin"))])
async def update_room(
    room_id: uuid.UUID, payload: RoomUpdate, db: AsyncSession = Depends(get_db)
) -> dict:
    room = await service.update_room(
        db, room_id, room_number=payload.room_number, is_active=payload.is_active
    )
    return RoomOut.model_validate(room).model_dump(mode="json")

 
# ---------------- GET DEPARTMENT ----------------
@router.get("/{department_id}")
async def get_department(
    department_id: uuid.UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> dict:
    dept = await service.get_department(db, department_id)
    return DepartmentOut.model_validate(dept).model_dump(mode="json")
 
 
# ---------------- UPDATE DEPARTMENT ----------------
@router.patch("/{department_id}", dependencies=[Depends(require_roles("admin"))])
async def update_department(
    department_id: uuid.UUID, payload: DepartmentUpdate, db: AsyncSession = Depends(get_db)
) -> dict:
    dept = await service.update_department(
        db,
        department_id,
        name=payload.name,
        code=payload.code,
        is_active=payload.is_active,
    )
    return DepartmentOut.model_validate(dept).model_dump(mode="json")

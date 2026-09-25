"""Department and Room CRUD.

No delete endpoints — is_active flag convention.
"""
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.departments.models import Department, Room
from app.users.models import Facility

MAX_PAGE_SIZE = 100


def _clamp_page_size(page_size: int) -> int:
    return min(max(page_size, 1), MAX_PAGE_SIZE)


# --------------------------------------------------------------------------- #
# DEPARTMENTS
# --------------------------------------------------------------------------- #

async def create_department(
    db: AsyncSession, name: str, code: str, facility_id: uuid.UUID,
    name_hi: str | None = None,
) -> Department:
    facility = await db.get(Facility, facility_id)
    if facility is None:
        raise HTTPException(404, "Facility not found")

    existing = (
        await db.execute(select(Department).where(Department.code == code, Department.facility_id == facility_id))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, f"Department code '{code}' already exists at this facility")

    dept = Department(
        id=uuid.uuid4(),
        name=name,
        name_hi=name_hi,
        code=code,
        facility_id=facility_id,
    )
    db.add(dept)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, f"Department code '{code}' already exists at this facility")
    await db.refresh(dept)
    return dept


async def get_department(
    db: AsyncSession,
    department_id: uuid.UUID,
    facility_id: uuid.UUID | None = None,
) -> Department:
    statement = select(Department).where(Department.id == department_id)
    if facility_id is not None:
        statement = statement.where(Department.facility_id == facility_id)
    dept = (await db.execute(statement)).scalar_one_or_none()
    if dept is None:
        raise HTTPException(404, "Department not found")
    return dept


async def list_departments(
    db: AsyncSession,
    facility_id: uuid.UUID | None,
    is_active: bool | None,
    page: int,
    page_size: int,
) -> tuple[list[Department], int]:
    page = max(page, 1)
    page_size = _clamp_page_size(page_size)

    q = select(Department)
    count_q = select(func.count()).select_from(Department)
    if facility_id is not None:
        q = q.where(Department.facility_id == facility_id)
        count_q = count_q.where(Department.facility_id == facility_id)
    if is_active is not None:
        q = q.where(Department.is_active == is_active)
        count_q = count_q.where(Department.is_active == is_active)

    total = (await db.execute(count_q)).scalar_one()
    q = q.order_by(Department.name).offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(q)).scalars().all()
    return items, total


async def update_department(
    db: AsyncSession,
    department_id: uuid.UUID,
    name: str | None,
    code: str | None,
    is_active: bool | None,
    facility_id: uuid.UUID | None = None,
    name_hi: str | None = None,
    *,
    update_name_hi: bool = False,
) -> Department:
    dept = await get_department(db, department_id, facility_id)

    if code is not None and code != dept.code:
        existing = (
            await db.execute(select(Department).where(Department.code == code, Department.facility_id == dept.facility_id))
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(409, f"Department code '{code}' already exists at this facility")
        dept.code = code

    if name is not None:
        dept.name = name
    if update_name_hi:
        dept.name_hi = name_hi
    if is_active is not None:
        dept.is_active = is_active

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, f"Department code '{code}' already exists at this facility")    
    await db.refresh(dept)
    return dept


# --------------------------------------------------------------------------- #
# ROOMS
# --------------------------------------------------------------------------- #

async def create_room(
    db: AsyncSession,
    department_id: uuid.UUID,
    room_number: str,
    facility_id: uuid.UUID | None = None,
) -> Room:
    dept = await get_department(db, department_id, facility_id)

    existing = (
        await db.execute(
            select(Room).where(
                Room.department_id == department_id, Room.room_number == room_number
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            409, f"Room '{room_number}' already exists in department '{dept.code}'"
        )

    room = Room(id=uuid.uuid4(), department_id=department_id, room_number=room_number)
    db.add(room)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            409, f"Room '{room_number}' already exists in department '{dept.code}'"
        )
    await db.refresh(room)
    return room


async def get_room(
    db: AsyncSession,
    room_id: uuid.UUID,
    facility_id: uuid.UUID | None = None,
) -> Room:
    statement = select(Room).join(Department).where(Room.id == room_id)
    if facility_id is not None:
        statement = statement.where(Department.facility_id == facility_id)
    room = (await db.execute(statement)).scalar_one_or_none()
    if room is None:
        raise HTTPException(404, "Room not found")
    return room


async def list_rooms(
    db: AsyncSession,
    department_id: uuid.UUID | None,
    is_active: bool | None,
    page: int,
    page_size: int,
    facility_id: uuid.UUID | None = None,
) -> tuple[list[Room], int]:
    page = max(page, 1)
    page_size = _clamp_page_size(page_size)

    q = select(Room)
    count_q = select(func.count()).select_from(Room)
    if facility_id is not None:
        q = q.join(Department).where(Department.facility_id == facility_id)
        count_q = count_q.join(Department).where(Department.facility_id == facility_id)
    if department_id is not None:
        q = q.where(Room.department_id == department_id)
        count_q = count_q.where(Room.department_id == department_id)
    if is_active is not None:
        q = q.where(Room.is_active == is_active)
        count_q = count_q.where(Room.is_active == is_active)

    total = (await db.execute(count_q)).scalar_one()
    q = q.order_by(Room.room_number).offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(q)).scalars().all()
    return items, total


async def update_room(
    db: AsyncSession,
    room_id: uuid.UUID,
    room_number: str | None,
    is_active: bool | None,
    facility_id: uuid.UUID | None = None,
) -> Room:
    room = await get_room(db, room_id, facility_id)

    if room_number is not None and room_number != room.room_number:
        existing = (
            await db.execute(
                select(Room).where(
                    Room.department_id == room.department_id,
                    Room.room_number == room_number,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(
                409, f"Room '{room_number}' already exists in this department"
            )
        room.room_number = room_number

    if is_active is not None:
        room.is_active = is_active

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, f"Room '{room_number}' already exists in this department")    
    await db.refresh(room)
    return room

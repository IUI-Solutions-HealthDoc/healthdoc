import uuid
from pydantic import BaseModel, ConfigDict


class DepartmentCreate(BaseModel):
    name: str
    code: str
    facility_id: uuid.UUID


class DepartmentOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    facility_id: uuid.UUID
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class DepartmentUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    is_active: bool | None = None


class DepartmentListOut(BaseModel):
    items: list[DepartmentOut]
    page: int
    page_size: int
    total: int


class RoomCreate(BaseModel):
    department_id: uuid.UUID
    room_number: str


class RoomOut(BaseModel):
    id: uuid.UUID
    department_id: uuid.UUID
    room_number: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class RoomUpdate(BaseModel):
    room_number: str | None = None
    is_active: bool | None = None
 
 
class RoomListOut(BaseModel):
    items: list[RoomOut]
    page: int
    page_size: int
    total: int
 

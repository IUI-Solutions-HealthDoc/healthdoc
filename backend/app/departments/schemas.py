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


class RoomCreate(BaseModel):
    department_id: uuid.UUID
    room_number: str


class RoomOut(BaseModel):
    id: uuid.UUID
    department_id: uuid.UUID
    room_number: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)

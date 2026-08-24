import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("name")
    @classmethod
    def _normalise_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("name must contain at least two non-whitespace characters")
        return value

    @field_validator("code")
    @classmethod
    def _normalise_code(cls, value: str) -> str:
        return value.upper()


class DepartmentOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    facility_id: uuid.UUID
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    code: str | None = Field(
        default=None, min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_-]+$"
    )
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _normalise_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) < 2:
            raise ValueError("name must contain at least two non-whitespace characters")
        return value

    @field_validator("code")
    @classmethod
    def _normalise_code(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class DepartmentListOut(BaseModel):
    items: list[DepartmentOut]
    page: int
    page_size: int
    total: int


class RoomCreate(BaseModel):
    department_id: uuid.UUID
    room_number: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9 _./-]+$")


class RoomOut(BaseModel):
    id: uuid.UUID
    department_id: uuid.UUID
    room_number: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class RoomUpdate(BaseModel):
    room_number: str | None = Field(
        default=None, min_length=1, max_length=30, pattern=r"^[A-Za-z0-9 _./-]+$"
    )
    is_active: bool | None = None
 
 
class RoomListOut(BaseModel):
    items: list[RoomOut]
    page: int
    page_size: int
    total: int
 

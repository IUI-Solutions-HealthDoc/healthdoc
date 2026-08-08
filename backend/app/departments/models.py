import uuid
from sqlalchemy import String, Text, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.common.db import Base
from app.common.models import Timestamps, UUIDPk


class Department(Base, UUIDPk, Timestamps):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("facility_id", "code", name="uq_department_facility_code"),
    )

    name: Mapped[str] = mapped_column(Text(), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    
    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    rooms: Mapped[list["Room"]] = relationship(back_populates="department")


class Room(Base, UUIDPk, Timestamps):
    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint("department_id", "room_number", name="uq_room_per_department"),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    room_number: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    department: Mapped["Department"] = relationship(back_populates="rooms")

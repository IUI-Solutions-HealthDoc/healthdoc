"""facilities + users models — migration 0002. See docs/database-schema.md §3."""
import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk


class Facility(Base, UUIDPk, Timestamps):
    __tablename__ = "facilities"

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    state_code: Mapped[str] = mapped_column(String(5), nullable=False)
    district: Mapped[str | None] = mapped_column(Text)
    facility_type: Mapped[str | None] = mapped_column(String(50))
    hfr_facility_id: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class User(Base, UUIDPk, Timestamps):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("facility_id", "employee_id", name="uq_users_facility_id_employee_id"),
    )

    keycloak_sub: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    mobile: Mapped[str | None] = mapped_column(String(20))
    designation: Mapped[str | None] = mapped_column(String(100))
    employee_id: Mapped[str | None] = mapped_column(String(30))
    registration_number: Mapped[str | None] = mapped_column(String(50))
    qualification: Mapped[str | None] = mapped_column(String(100))
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # department_id is added by migration 0005 (departments module) — B4 adds the
    # mapped column here in the same PR.

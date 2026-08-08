"""facilities + users models — migration 0002. See docs/database-schema.md §3."""
import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, event, text
from datetime import datetime
import zoneinfo
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk


class Facility(Base, UUIDPk, Timestamps):
    __tablename__ = "facilities"

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    state_code: Mapped[str] = mapped_column(String(5), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, server_default="Asia/Kolkata")
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

    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # department_id is added by migration 0005 (departments module) — B4 adds the
    # mapped column here in the same PR.




@event.listens_for(Facility, "after_insert")
def _create_uhid_sequence_for_facility(mapper, connection, target: Facility) -> None:
    """Create the UHID sequence for this facility+year at insert time so the
    registration endpoint never needs to run DDL inside a request path.

    Postgres only. SEQUENCE is not SQL that SQLite understands, and this hook
    fires on EVERY Facility insert — including the one in tests/conftest.py's
    `seed` fixture, which runs against in-memory SQLite. Without this guard the
    whole queue suite errors at setup with 'near "SEQUENCE": syntax error', in
    tests that have nothing to do with patients or UHIDs. Skipping is correct
    rather than merely convenient: those tests never call generate_uhid(), and
    _next_sequence() creates the sequence on demand if one is ever missing.
    """
    if connection.dialect.name != "postgresql":
        return
    try:
        tz = zoneinfo.ZoneInfo(target.timezone or "Asia/Kolkata")
    except Exception:
        tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    year = datetime.now(tz).year
    safe_code = (target.code or "").lower().replace("-", "_")
    if not safe_code:
        return
    seq_name = f"seq_uhid_{safe_code}_{year}"
    connection.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{seq_name}"'))

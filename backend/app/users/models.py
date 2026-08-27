"""facilities + users models — migration 0002. See docs/database-schema.md §3."""
import re
import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, event, text
from datetime import datetime
import zoneinfo
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk

#: Same charset as app/patients/service.py and app/emergency/service.py.
#: Three copies of one rule is two too many, but a shared constant would
#: put a models module on the import path of two service modules; the
#: duplication is deliberate and cross-referenced in each comment.
_FACILITY_CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,20}$")


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
    raw_code = (target.code or "").lower().replace("-", "_")
    if not raw_code:
        return
    # CREATE SEQUENCE cannot take its name as a bind parameter, so this
    # allowlist is the only thing between facilities.code and SQL injection
    # into a DDL string. `.replace("-", "_")` is a normalisation, NOT a
    # sanitiser: it says nothing about a quote, a semicolon or a newline.
    #
    # app/patients/service.py and app/emergency/service.py both validate the
    # same value against the same charset before interpolating it. This site
    # did not, and it is the one that runs automatically on every facility
    # INSERT — so any future facility-creation endpoint would have inherited
    # the gap without anyone writing a new line of SQL.
    #
    # Raising aborts the insert on purpose: a facility whose code cannot form
    # a safe identifier should not exist, and failing at creation is far
    # cheaper than discovering it when UHID allocation breaks.
    if not _FACILITY_CODE_RE.match(raw_code):
        raise ValueError(f"facilities.code contains invalid characters: {target.code!r}")
    seq_name = f"seq_uhid_{raw_code}_{year}"
    connection.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{seq_name}"'))

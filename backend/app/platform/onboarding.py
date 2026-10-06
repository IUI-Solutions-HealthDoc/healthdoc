"""Bring a new facility into an existing deployment: the superadmin's job.

Three steps, each explicit and each refusing to run twice:

  1. create the facility (code, name, state, timezone, ownership, HFR id)
  2. create its first admin: Keycloak first, as everywhere, then the users
     row at that facility. That admin adds the rest of the staff through
     the ordinary Users screen, which creates accounts at its own facility.
  3. copy the setup of an existing facility: departments, their rooms,
     wards, stock locations and the current tariff. Catalogues that are
     already shared (lab analytes, vaccines, drugs) are not copied. Tariff
     rows are authored by the new facility's admin, because a superadmin is
     not a user of any facility, and a price list must name who set it.

Speaking to ABDM as this facility is separate and deliberate: its HFR id
must also be linked to the bridge at NHA and listed in
ABDM_ADDITIONAL_HFR_FACILITY_IDS (integrations/abdm/facilities.py).
"""

from __future__ import annotations

import re
import uuid
import zoneinfo
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import ChargeMaster
from app.users.models import Facility, User

#: HFR facility ids as NHA issues them: IN0910034387, IN2710005985.
HFR_ID = re.compile(r"^IN\d{10}$")
FACILITY_CODE = re.compile(r"^[A-Za-z0-9_]{1,20}$")


class OnboardingError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def check_timezone(name: str) -> str:
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise OnboardingError("invalid_timezone", f"Unknown timezone {name!r}", 422) from exc
    return name


async def _hfr_id_free(db: AsyncSession, hfr_id: str | None, *, except_id: uuid.UUID | None = None) -> None:
    """One facility per HFR id: two would make an ABDM callback ambiguous."""
    if hfr_id is None:
        return
    if not HFR_ID.match(hfr_id):
        raise OnboardingError("invalid_hfr_id", "An HFR facility id looks like IN0910034387", 422)
    held = (
        await db.execute(
            select(Facility.id).where(Facility.hfr_facility_id == hfr_id, Facility.id != except_id)
        )
    ).first()
    if held is not None:
        raise OnboardingError("hfr_id_in_use", "Another facility already has this HFR id")


async def create_facility(
    db: AsyncSession,
    *,
    code: str,
    name: str,
    state_code: str,
    timezone: str,
    ownership: str | None,
    hfr_facility_id: str | None,
    district: str | None = None,
) -> Facility:
    if not FACILITY_CODE.match(code):
        raise OnboardingError("invalid_code", "Use 1 to 20 letters, digits or underscores", 422)
    if (await db.execute(select(Facility.id).where(Facility.code == code))).first() is not None:
        raise OnboardingError("code_in_use", "Another facility already has this code")
    await _hfr_id_free(db, hfr_facility_id)
    facility = Facility(
        id=uuid.uuid4(), code=code, name=name.strip(), state_code=state_code, timezone=check_timezone(timezone),
        ownership=ownership, hfr_facility_id=hfr_facility_id, district=district, is_active=True,
    )
    db.add(facility)
    await db.flush()
    return facility


async def update_facility(db: AsyncSession, facility: Facility, changes: dict) -> Facility:
    if "hfr_facility_id" in changes:
        await _hfr_id_free(db, changes["hfr_facility_id"], except_id=facility.id)
    if "timezone" in changes:
        check_timezone(changes["timezone"])
    for field, value in changes.items():
        setattr(facility, field, value.strip() if isinstance(value, str) and field == "name" else value)
    await db.flush()
    return facility


async def earliest_staff(db: AsyncSession, facility_id: uuid.UUID) -> User | None:
    """The facility's earliest active account: the admin the superadmin created."""
    return (
        await db.execute(
            select(User)
            .where(User.facility_id == facility_id, User.is_active.is_(True))
            .order_by(User.created_at, User.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def copy_setup(
    db: AsyncSession, *, source: Facility, target: Facility, author_id: uuid.UUID, today: date
) -> dict[str, int]:
    """Departments with their rooms, wards and stock locations re-pointed to
    the copies, and the tariff in force today. Refuses a facility that
    already has departments: a second copy would duplicate every one."""
    from sqlalchemy import text

    if source.id == target.id:
        raise OnboardingError("same_facility", "Copy the setup from another facility", 422)
    has = (
        await db.execute(text("SELECT count(*) FROM departments WHERE facility_id = :f"), {"f": target.id})
    ).scalar_one()
    if has:
        raise OnboardingError("setup_exists", "This facility already has departments")

    departments = (
        await db.execute(
            text("SELECT id, name, name_hi, code, is_active FROM departments WHERE facility_id = :f"),
            {"f": source.id},
        )
    ).all()
    mapping: dict[uuid.UUID, uuid.UUID] = {}
    for row in departments:
        mapping[row.id] = uuid.uuid4()
        await db.execute(
            text("INSERT INTO departments (id, name, name_hi, code, facility_id, is_active) "
                 "VALUES (:id, :name, :name_hi, :code, :f, :active)"),
            {"id": mapping[row.id], "name": row.name, "name_hi": row.name_hi, "code": row.code,
             "f": target.id, "active": row.is_active},
        )
    counts = {"departments": len(departments), "rooms": 0, "wards": 0, "stock_locations": 0, "tariff_rows": 0}
    for row in (await db.execute(
        text("SELECT r.department_id, r.room_number, r.is_active FROM rooms r "
             "JOIN departments d ON d.id = r.department_id WHERE d.facility_id = :f"), {"f": source.id},
    )).all():
        await db.execute(
            text("INSERT INTO rooms (id, department_id, room_number, is_active) VALUES (:id, :d, :n, :a)"),
            {"id": uuid.uuid4(), "d": mapping[row.department_id], "n": row.room_number, "a": row.is_active},
        )
        counts["rooms"] += 1
    for row in (await db.execute(
        text("SELECT name, name_hi, department_id, is_active FROM wards WHERE facility_id = :f"), {"f": source.id},
    )).all():
        await db.execute(
            text("INSERT INTO wards (id, name, name_hi, department_id, facility_id, is_active) "
                 "VALUES (:id, :name, :name_hi, :d, :f, :a)"),
            {"id": uuid.uuid4(), "name": row.name, "name_hi": row.name_hi,
             "d": mapping.get(row.department_id), "f": target.id, "a": row.is_active},
        )
        counts["wards"] += 1
    for row in (await db.execute(
        text("SELECT name, location_type, department_id FROM stock_locations WHERE facility_id = :f"),
        {"f": source.id},
    )).all():
        await db.execute(
            text("INSERT INTO stock_locations (id, name, location_type, department_id, facility_id) "
                 "VALUES (:id, :name, :t, :d, :f)"),
            {"id": uuid.uuid4(), "name": row.name, "t": row.location_type,
             "d": mapping.get(row.department_id), "f": target.id},
        )
        counts["stock_locations"] += 1
    tariff = (
        await db.execute(
            select(ChargeMaster).where(
                ChargeMaster.facility_id == source.id,
                ChargeMaster.is_active.is_(True),
                ChargeMaster.effective_from <= today,
                (ChargeMaster.effective_to.is_(None)) | (ChargeMaster.effective_to >= today),
            )
        )
    ).scalars().all()
    for row in tariff:
        db.add(ChargeMaster(
            id=uuid.uuid4(), facility_id=target.id, charge_code=row.charge_code, description=row.description,
            description_hi=row.description_hi, charge_category=row.charge_category, unit_price=row.unit_price,
            scheme_code=row.scheme_code, effective_from=today, effective_to=None, is_active=True,
            created_by=author_id,
        ))
        counts["tariff_rows"] += 1
    await db.flush()
    return counts


async def staff_count(db: AsyncSession, facility_id: uuid.UUID) -> int:
    return int((await db.execute(select(func.count()).where(User.facility_id == facility_id))).scalar_one())

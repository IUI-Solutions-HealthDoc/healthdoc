"""A superadmin brings a second facility into the deployment.

Create it, give it its first admin, copy another facility's setup. Each step
refuses to run twice, and an HFR id may name one facility only, or an ABDM
callback addressed to it would be ambiguous.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.billing.models import ChargeMaster
from app.platform import onboarding
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio
TODAY = date(2026, 10, 6)


def _code() -> str:
    return f"T{uuid.uuid4().hex[:8].upper()}"


async def _facility(db, **change) -> Facility:
    return await onboarding.create_facility(
        db, **{"code": _code(), "name": "Second Hospital", "state_code": "BR", "timezone": "Asia/Kolkata",
               "ownership": "private", "hfr_facility_id": None, **change}
    )


async def _staff(db, facility: Facility) -> User:
    user = User(id=uuid.uuid4(), keycloak_sub=f"sub-{uuid.uuid4()}", username=f"u{uuid.uuid4().hex[:8]}",
                full_name="First Admin", facility_id=facility.id, is_active=True)
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def source(db) -> Facility:
    facility = await _facility(db, name="First Hospital")
    author = await _staff(db, facility)
    department = uuid.uuid4()
    await db.execute(sa.text("INSERT INTO departments (id, name, code, facility_id) VALUES (:id, 'Radiology', 'RAD', :f)"),
                     {"id": department, "f": facility.id})
    await db.execute(sa.text("INSERT INTO rooms (id, department_id, room_number) VALUES (:id, :d, 'R1')"),
                     {"id": uuid.uuid4(), "d": department})
    await db.execute(sa.text("INSERT INTO wards (id, name, department_id, facility_id) VALUES (:id, 'General', :d, :f)"),
                     {"id": uuid.uuid4(), "d": department, "f": facility.id})
    await db.execute(sa.text("INSERT INTO stock_locations (id, name, location_type, department_id, facility_id) "
                             "VALUES (:id, 'Main store', 'central', NULL, :f)"), {"id": uuid.uuid4(), "f": facility.id})
    for code, price, frm, to in (("XRAY-CHEST", "450.00", date(2026, 1, 1), None),
                                 ("OLD-FEE", "100.00", date(2025, 1, 1), date(2025, 12, 31))):
        db.add(ChargeMaster(id=uuid.uuid4(), facility_id=facility.id, charge_code=code, description=code,
                            charge_category="radiology", unit_price=Decimal(price), effective_from=frm,
                            effective_to=to, is_active=True, created_by=author.id))
    await db.flush()
    return facility


async def test_a_facility_is_created_with_its_hfr_id(db):
    facility = await _facility(db, hfr_facility_id="IN2710009999")
    assert facility.is_active and facility.hfr_facility_id == "IN2710009999"


@pytest.mark.parametrize("change,code", [
    ({"code": "has space"}, "invalid_code"),
    ({"hfr_facility_id": "2710009999"}, "invalid_hfr_id"),
    ({"timezone": "Mars/Olympus"}, "invalid_timezone"),
])
async def test_a_malformed_facility_is_refused(db, change, code):
    with pytest.raises(onboarding.OnboardingError) as refused:
        await _facility(db, **change)
    assert refused.value.code == code


async def test_an_hfr_id_names_one_facility_only(db):
    first = await _facility(db, hfr_facility_id="IN2710008888")
    with pytest.raises(onboarding.OnboardingError, match="HFR id"):
        await _facility(db, hfr_facility_id="IN2710008888")
    second = await _facility(db)
    with pytest.raises(onboarding.OnboardingError, match="HFR id"):
        await onboarding.update_facility(db, second, {"hfr_facility_id": "IN2710008888"})
    await onboarding.update_facility(db, first, {"hfr_facility_id": "IN2710008888"})  # its own is fine


async def test_setup_is_copied_with_departments_repointed_and_todays_tariff(db, source):
    target = await _facility(db)
    admin = await _staff(db, target)
    counts = await onboarding.copy_setup(db, source=source, target=target, author_id=admin.id, today=TODAY)
    assert counts == {"departments": 1, "rooms": 1, "wards": 1, "stock_locations": 1, "tariff_rows": 1}
    department = (await db.execute(sa.text("SELECT id FROM departments WHERE facility_id = :f"),
                                   {"f": target.id})).scalar_one()
    ward = (await db.execute(sa.text("SELECT department_id FROM wards WHERE facility_id = :f"),
                             {"f": target.id})).scalar_one()
    room = (await db.execute(sa.text("SELECT department_id FROM rooms WHERE department_id = :d"),
                             {"d": department})).scalar_one()
    assert ward == room == department, "copies point at the copied department, not the source's"
    tariff = (await db.execute(sa.select(ChargeMaster).where(ChargeMaster.facility_id == target.id))).scalars().all()
    assert [(t.charge_code, t.unit_price, t.effective_from, t.created_by) for t in tariff] == [
        ("XRAY-CHEST", Decimal("450.00"), TODAY, admin.id)
    ], "only the tariff in force, authored by the new facility's admin"


async def test_setup_is_never_copied_twice_or_onto_itself(db, source):
    target = await _facility(db)
    admin = await _staff(db, target)
    await onboarding.copy_setup(db, source=source, target=target, author_id=admin.id, today=TODAY)
    with pytest.raises(onboarding.OnboardingError) as twice:
        await onboarding.copy_setup(db, source=source, target=target, author_id=admin.id, today=TODAY)
    assert twice.value.code == "setup_exists"
    with pytest.raises(onboarding.OnboardingError) as itself:
        await onboarding.copy_setup(db, source=source, target=source, author_id=admin.id, today=TODAY)
    assert itself.value.code == "same_facility"


async def test_the_copy_author_is_the_facilitys_first_account(db):
    target = await _facility(db)
    assert await onboarding.earliest_staff(db, target.id) is None
    admin = await _staff(db, target)
    later = await _staff(db, target)
    await db.execute(sa.text("UPDATE users SET created_at = created_at + interval '1 minute' WHERE id = :id"),
                     {"id": later.id})
    assert (await onboarding.earliest_staff(db, target.id)).id == admin.id

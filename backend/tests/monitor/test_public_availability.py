"""Public bed and blood availability: opted-in facilities only, counts only,
and blood that could actually be issued."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.availability import router as availability
from app.monitor import service
from app.monitor.models import FacilityPulse
from app.users.models import Facility

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _pinned_clock(monkeypatch):
    monkeypatch.setattr(service, "utcnow", lambda: NOW)


async def _facility(db, *, publish=True, district="Patna", name="Hospital"):
    facility = Facility(id=uuid.uuid4(), code=f"P{uuid.uuid4().hex[:6].upper()}", name=name, state_code="BR",
                        district=district, timezone="Asia/Kolkata", publish_availability=publish)
    db.add(facility)
    await db.flush()
    return facility


async def _pulse(db, facility, *, at=NOW, beds=10, admitted=4, detail=None):
    db.add(FacilityPulse(
        id=uuid.uuid4(), facility_id=facility.id, captured_at=at, opd_today=50, queue_waiting=3,
        emergency_open=2, admitted_now=admitted, beds_total=beds, lab_pending=1, stock_below_reorder=0,
        batches_expiring_30d=0, staff_rostered_today=4,
        detail=detail or {"wards": [{"ward": "General", "department": None, "beds": beds, "occupied": admitted,
                                     "free": beds - admitted, "maintenance": 0}],
                          "blood": {"b_pos": 3}, "staff": [{"name": "Dr Hidden"}]},
    ))
    await db.flush()


async def test_only_opted_in_facilities_are_listed_with_counts_only(db):
    shown = await _facility(db, name="Shown DH")
    hidden = await _facility(db, publish=False, name="Hidden DH")
    await _pulse(db, shown)
    await _pulse(db, hidden)
    out = await availability.public_availability(db=db, state="br", district=None)
    names = [f.name for f in out.facilities]
    assert "Shown DH" in names and "Hidden DH" not in names
    row = next(f for f in out.facilities if f.name == "Shown DH")
    assert (row.beds_free, row.beds_total, row.blood, row.stale) == (6, 10, {"b_pos": 3}, False)
    assert "Dr Hidden" not in out.model_dump_json()  # staff detail never leaves the capture


async def test_a_stale_capture_is_marked_and_the_district_filter_applies(db):
    patna = await _facility(db, district="Patna", name="Old Patna")
    gaya = await _facility(db, district="Gaya", name="Gaya DH")
    await _pulse(db, patna, at=NOW - timedelta(hours=2))
    await _pulse(db, gaya)
    out = await availability.public_availability(db=db, state="BR", district="patna")
    assert [f.name for f in out.facilities] == ["Old Patna"]
    assert out.facilities[0].stale is True


async def test_only_issuable_blood_is_counted(db):
    facility = await _facility(db)
    user, donor = uuid.uuid4(), uuid.uuid4()
    await db.execute(sa.text("INSERT INTO users (id, keycloak_sub, username, full_name, facility_id) "
                             "VALUES (:u, :s, :n, 'Blood Officer', :f)"),
                     {"u": user, "s": str(uuid.uuid4()), "n": f"b{uuid.uuid4().hex[:8]}", "f": facility.id})
    await db.execute(sa.text("INSERT INTO blood_donors (id, full_name, blood_group, created_by) "
                             "VALUES (:d, 'Donor', 'o_pos', :u)"), {"d": donor, "u": user})
    today = date(2026, 10, 10)
    for group, status, screening, expiry in [
        ("o_pos", "available", "passed", today + timedelta(days=20)),  # counts
        ("o_pos", "available", "passed", today + timedelta(days=1)),   # counts
        ("o_pos", "available", "pending", today + timedelta(days=20)), # not screened
        ("a_neg", "issued", "passed", today + timedelta(days=20)),     # already issued
        ("a_neg", "available", "passed", today - timedelta(days=1)),   # expired
    ]:
        await db.execute(sa.text("INSERT INTO blood_units (id, donor_id, bag_number, blood_group, volume_ml, "
                                 "expiry_date, status, screening_status) VALUES (:id, :d, :b, :g, 350, :e, :s, :sc)"),
                         {"id": uuid.uuid4(), "d": donor, "b": uuid.uuid4().hex[:12], "g": group, "e": expiry,
                          "s": status, "sc": screening})
    await db.flush()
    pulse = await service.capture_facility(db, facility, now=NOW)
    assert pulse.detail["blood"] == {"o_pos": 2}


async def test_the_superadmin_switches_publishing_on_and_off(db):
    from app.platform import router as platform_router

    facility = await _facility(db, publish=False, name="Toggle DH")
    await _pulse(db, facility)
    await platform_router.update_platform_facility(
        facility.id, platform_router.PlatformFacilityUpdate(publish_availability=True), db=db
    )
    assert "Toggle DH" in [f.name for f in (await availability.public_availability(db=db, state="BR", district=None)).facilities]
    await platform_router.update_platform_facility(
        facility.id, platform_router.PlatformFacilityUpdate(publish_availability=False), db=db
    )
    assert "Toggle DH" not in [f.name for f in (await availability.public_availability(db=db, state="BR", district=None)).facilities]

"""Control room: what an officer can see, and whether the counts are true.

The scope tests matter most. A district officer seeing another district's
hospitals is a data leak; an officer with no grant seeing an empty board would
read as "all quiet". Both are asserted.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi import HTTPException

from app.auth.deps import AuthUser
from app.monitor import router as monitor_router
from app.monitor import service
from app.monitor.models import FacilityPulse, MonitorScope
from app.users.models import Facility

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)  # 11:30 IST


async def _facility(db, *, state="BR", district="Patna", name="Facility") -> Facility:
    facility = Facility(
        id=uuid.uuid4(), code=f"M{uuid.uuid4().hex[:6].upper()}", name=name,
        state_code=state, district=district, timezone="Asia/Kolkata",
    )
    db.add(facility)
    await db.flush()
    return facility


async def _grant(db, sub, state, district=None):
    db.add(MonitorScope(
        id=uuid.uuid4(), keycloak_sub=sub, username=f"m-{sub[:6]}", state_code=state,
        district=district, granted_by_sub="platform",
    ))
    await db.flush()


def _officer(sub):
    return AuthUser(sub=sub, username="officer", roles=["monitor"])


async def _pulse(db, facility, **counts):
    base = dict(
        opd_today=0, queue_waiting=0, emergency_open=0, admitted_now=0, beds_total=0,
        lab_pending=0, stock_below_reorder=0, batches_expiring_30d=0, staff_rostered_today=0,
    )
    base.update(counts)
    db.add(FacilityPulse(id=uuid.uuid4(), facility_id=facility.id, captured_at=NOW, **base))
    await db.flush()


@pytest.fixture(autouse=True)
def _pinned_clock(monkeypatch):
    monkeypatch.setattr(service, "utcnow", lambda: NOW)


async def _board(db, sub, district=None):
    return await monitor_router.get_board(user=_officer(sub), db=db, district=district)


# ---------------------------------------------------------------- scope


async def test_a_district_officer_sees_only_their_district(db):
    patna = await _facility(db, district="Patna", name="Patna DH")
    gaya = await _facility(db, district="Gaya", name="Gaya DH")
    await _pulse(db, patna, opd_today=40)
    await _pulse(db, gaya, opd_today=70)
    sub = str(uuid.uuid4())
    await _grant(db, sub, "BR", "patna")  # names compare case-blind
    board = await _board(db, sub)
    ids = {row.facility_id for row in board.facilities}
    assert patna.id in ids and gaya.id not in ids
    assert board.totals.opd_today == sum(r.opd_today for r in board.facilities)


async def test_a_state_officer_sees_the_state_and_nothing_beyond(db):
    patna = await _facility(db, district="Patna")
    other_state = await _facility(db, state="UP", district="Lucknow")
    sub = str(uuid.uuid4())
    await _grant(db, sub, "BR")
    ids = {row.facility_id for row in (await _board(db, sub)).facilities}
    assert patna.id in ids and other_state.id not in ids


async def test_no_grant_is_refused_not_shown_empty(db):
    await _facility(db)
    with pytest.raises(HTTPException) as refused:
        await _board(db, str(uuid.uuid4()))
    assert refused.value.status_code == 403
    assert refused.value.detail["code"] == "monitor_scope_missing"


async def test_a_district_filter_cannot_widen_the_scope(db):
    await _facility(db, district="Patna")
    gaya = await _facility(db, district="Gaya")
    sub = str(uuid.uuid4())
    await _grant(db, sub, "BR", "Patna")
    board = await _board(db, sub, district="Gaya")
    assert board.facilities == []
    assert gaya.id not in {row.facility_id for row in board.facilities}


async def test_a_facility_that_never_reported_is_grey_not_green(db):
    silent = await _facility(db, district="Patna")
    sub = str(uuid.uuid4())
    await _grant(db, sub, "BR")
    row = next(r for r in (await _board(db, sub)).facilities if r.facility_id == silent.id)
    assert row.status == "grey" and row.opd_today is None


# ---------------------------------------------------------------- status


def _p(**counts):
    base = dict(
        opd_today=0, queue_waiting=0, emergency_open=0, admitted_now=0, beds_total=0,
        lab_pending=0, stock_below_reorder=0, batches_expiring_30d=0, staff_rostered_today=1,
    )
    base.update(counts)
    return FacilityPulse(facility_id=uuid.uuid4(), captured_at=NOW, **base)


@pytest.mark.parametrize(
    ("counts", "status"),
    [
        ({}, "green"),
        ({"beds_total": 100, "admitted_now": 80}, "amber"),
        ({"beds_total": 100, "admitted_now": 95}, "red"),
        ({"stock_below_reorder": 2}, "amber"),
        ({"stock_below_reorder": 5}, "red"),
        ({"staff_rostered_today": 0, "opd_today": 12}, "amber"),
    ],
)
async def test_status_colour_and_its_reason(counts, status):
    colour, reasons = service.status_of(_p(**counts), now=NOW)
    assert colour == status
    assert (reasons == []) == (status == "green")


async def test_a_stale_capture_reads_as_not_reporting():
    stale = _p()
    stale.captured_at = NOW - timedelta(minutes=46)
    assert service.status_of(stale, now=NOW) == ("grey", ["not reporting"])


# ---------------------------------------------------------------- capture


async def test_capture_counts_from_the_source_tables(db):
    facility = await _facility(db)
    fid = facility.id
    user, patient, dept = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    run = db.execute
    await run(sa.text("INSERT INTO users (id, keycloak_sub, username, full_name, facility_id) "
                      "VALUES (:u, :s, :n, 'Doctor', :f)"),
              {"u": user, "s": str(uuid.uuid4()), "n": f"d{uuid.uuid4().hex[:8]}", "f": fid})
    await run(sa.text("INSERT INTO patients (id, full_name, sex, identity_path, facility_id, created_by, "
                      "age_years, uhid) VALUES (:p, 'Pulse Patient', 'other', 'demographics_only', :f, :u, 30, :h)"),
              {"p": patient, "f": fid, "u": user, "h": f"IN-BR-{uuid.uuid4().hex[:10]}"})
    today_ist = date(2026, 10, 10)
    visits = {}
    for key, vtype, status, at in [
        ("opd1", "opd", "waiting", NOW - timedelta(hours=1)),
        ("opd2", "opd", "completed", NOW - timedelta(hours=2)),
        ("opd_yesterday", "opd", "completed", NOW - timedelta(days=1)),
        ("ed_open", "emergency", "in_service", NOW - timedelta(hours=3)),
        ("ed_closed", "emergency", "completed", NOW - timedelta(hours=3)),
        ("ipd", "ipd", "in_service", NOW - timedelta(days=2)),
    ]:
        visits[key] = uuid.uuid4()
        await run(sa.text("INSERT INTO visits (id, visit_number, patient_id, facility_id, visit_type, "
                          "status, visit_date, created_by) VALUES (:id, :n, :p, :f, :t, :s, :d, :u)"),
                  {"id": visits[key], "n": f"V-{uuid.uuid4().hex[:10]}", "p": patient, "f": fid,
                   "t": vtype, "s": status, "d": at, "u": user})
    ward = uuid.uuid4()
    await run(sa.text("INSERT INTO wards (id, name, facility_id) VALUES (:w, 'General', :f)"), {"w": ward, "f": fid})
    beds = [uuid.uuid4() for _ in range(4)]
    for i, bed in enumerate(beds):
        await run(sa.text("INSERT INTO beds (id, ward_id, bed_number, status) VALUES (:b, :w, :n, :s)"),
                  {"b": bed, "w": ward, "n": f"B{i}", "s": "maintenance" if i == 3 else "vacant"})
    # Mirror says vacant; the admission is the truth.
    await run(sa.text("INSERT INTO admissions (id, visit_id, patient_id, ward_id, bed_id, admitted_at, "
                      "created_by, status) VALUES (:a, :v, :p, :w, :b, :t, :u, 'admitted')"),
              {"a": uuid.uuid4(), "v": visits["ipd"], "p": patient, "w": ward, "b": beds[0],
               "t": NOW - timedelta(days=2), "u": user})
    await run(sa.text("INSERT INTO departments (id, name, code, facility_id) VALUES (:d, 'Medicine', :c, :f)"),
              {"d": dept, "c": f"MED{uuid.uuid4().hex[:4]}", "f": fid})
    await run(sa.text("INSERT INTO rosters (id, staff_user_id, department_id, shift, roster_date) "
                      "VALUES (:r, :u, :d, 'morning', :day)"),
              {"r": uuid.uuid4(), "u": user, "d": dept, "day": today_ist})
    location = uuid.uuid4()
    await run(sa.text("INSERT INTO stock_locations (id, name, facility_id) VALUES (:l, 'Main store', :f)"),
              {"l": location, "f": fid})
    low, fine = uuid.uuid4(), uuid.uuid4()
    for item, reorder in ((low, 100), (fine, 10)):
        await run(sa.text("INSERT INTO inventory_items (id, name, reorder_level) VALUES (:i, :n, :r)"),
                  {"i": item, "n": f"Drug {uuid.uuid4().hex[:4]}", "r": reorder})
    for item, qty, expiry in [
        (low, 30, today_ist + timedelta(days=10)),    # low and expiring soon
        (low, 500, today_ist - timedelta(days=1)),    # expired: must not hide the shortage
        (fine, 50, today_ist + timedelta(days=200)),
    ]:
        await run(sa.text("INSERT INTO inventory_batches (id, item_id, batch_number, expiry_date, quantity, "
                          "stock_location_id) VALUES (:b, :i, :n, :e, :q, :l)"),
                  {"b": uuid.uuid4(), "i": item, "n": uuid.uuid4().hex[:8], "e": expiry, "q": qty, "l": location})
    await db.flush()

    pulse = await service.capture_facility(db, facility, now=NOW)
    assert (pulse.opd_today, pulse.emergency_open, pulse.admitted_now, pulse.beds_total) == (2, 1, 1, 3)
    assert pulse.stock_below_reorder == 1
    assert pulse.batches_expiring_30d == 1
    assert pulse.staff_rostered_today == 1
    # The drill-down: names an officer can act on, no patients.
    assert pulse.detail["wards"] == [
        {"ward": "General", "department": None, "beds": 3, "occupied": 1, "free": 2, "maintenance": 1}
    ]
    [short] = pulse.detail["stock_short"]
    assert (short["available"], short["reorder_level"]) == ("30.00", "100.00")
    [expiring] = pulse.detail["expiring"]
    assert expiring["expiry"] == (today_ist + timedelta(days=10)).isoformat()
    assert "Pulse Patient" not in str(pulse.detail)


# ---------------------------------------------------------------- granting areas (superadmin)


from app.platform import router as platform_router  # noqa: E402

PLATFORM = AuthUser(sub="platform-owner", username="root", roles=["superadmin"])


async def test_a_new_officer_gets_only_the_monitor_role_and_an_area(db, monkeypatch):
    created = {}

    class _Keycloak:
        async def create_user(self, **kwargs):
            created.update(kwargs)
            return "kc-officer-1"

    monkeypatch.setattr(platform_router, "KeycloakAdmin", _Keycloak)
    out = await platform_router.create_platform_monitor(
        platform_router.PlatformMonitorCreate(
            username="patna.officer", full_name="Patna Officer", temporary_password="Temp#12345",
            state_code="BR", district=" Patna ",
        ),
        user=PLATFORM, db=db,
    )
    assert created["roles"] == ["monitor"]
    assert (out.keycloak_sub, out.state_code, out.district) == ("kc-officer-1", "BR", "Patna")


async def test_the_same_area_cannot_be_granted_twice(db):
    await _grant(db, "kc-officer-2", "BR")
    # NULL district: the partial unique index and the router both refuse it.
    with pytest.raises(HTTPException) as refused:
        await platform_router.add_monitor_scope(
            "kc-officer-2", platform_router.MonitorAreaIn(state_code="BR"), user=PLATFORM, db=db
        )
    assert refused.value.status_code == 409
    added = await platform_router.add_monitor_scope(
        "kc-officer-2", platform_router.MonitorAreaIn(state_code="BR", district="Gaya"), user=PLATFORM, db=db
    )
    assert added.district == "Gaya"


async def test_an_area_for_an_unknown_officer_is_refused(db):
    with pytest.raises(HTTPException) as refused:
        await platform_router.add_monitor_scope(
            "nobody", platform_router.MonitorAreaIn(state_code="BR"), user=PLATFORM, db=db
        )
    assert refused.value.status_code == 404


async def test_removing_the_last_area_closes_the_board(db):
    facility = await _facility(db)
    await _pulse(db, facility)
    await _grant(db, "kc-officer-3", "BR")
    scope = (await db.execute(sa.select(MonitorScope).where(MonitorScope.keycloak_sub == "kc-officer-3"))).scalar_one()
    await platform_router.remove_monitor_scope(scope.id, user=PLATFORM, db=db)
    with pytest.raises(HTTPException) as refused:
        await _board(db, "kc-officer-3")
    assert refused.value.status_code == 403


# ---------------------------------------------------------------- drill-down


async def test_the_drill_down_is_404_outside_the_grant(db):
    mine = await _facility(db, district="Patna")
    theirs = await _facility(db, district="Gaya")
    await _pulse(db, mine)
    sub = str(uuid.uuid4())
    await _grant(db, sub, "BR", "Patna")
    detail = await monitor_router.get_facility_detail(mine.id, user=_officer(sub), db=db)
    assert detail.facility.facility_id == mine.id
    for other in (theirs.id, uuid.uuid4()):
        with pytest.raises(HTTPException) as refused:
            await monitor_router.get_facility_detail(other, user=_officer(sub), db=db)
        assert refused.value.status_code == 404


async def test_a_silent_facility_shows_no_stale_lists(db):
    facility = await _facility(db, district="Patna")
    db.add(FacilityPulse(
        id=uuid.uuid4(), facility_id=facility.id, captured_at=NOW - timedelta(hours=2),
        opd_today=0, queue_waiting=0, emergency_open=0, admitted_now=0, beds_total=0, lab_pending=0,
        stock_below_reorder=1, batches_expiring_30d=0, staff_rostered_today=0,
        detail={"stock_short": [{"item": "Old", "strength": None, "available": "0", "reorder_level": "5"}]},
    ))
    await db.flush()
    sub = str(uuid.uuid4())
    await _grant(db, sub, "BR")
    detail = await monitor_router.get_facility_detail(facility.id, user=_officer(sub), db=db)
    assert detail.facility.status == "grey" and detail.stock_short == []


# ---------------------------------------------------------------- disease trends


from app.monitor.models import DiagnosisDailyCount  # noqa: E402


async def _counts(db, facility, code, *, this_week, last_week, today=date(2026, 10, 10), version="icd10"):
    # Spread over two days per week so the weekly sum is what is asserted.
    for day, n in ((today, this_week), (today - timedelta(days=9), last_week)):
        if n:
            db.add(DiagnosisDailyCount(id=uuid.uuid4(), facility_id=facility.id, day=day,
                                       icd_version=version, icd_code=code, patients=n))
    await db.flush()


async def test_trends_hide_small_counts_and_flag_spikes(db):
    patna = await _facility(db, district="Patna")
    await _counts(db, patna, "A09", this_week=24, last_week=6)     # spike
    await _counts(db, patna, "J18", this_week=3, last_week=12)     # small this week
    await _counts(db, patna, "B54", this_week=9, last_week=1)      # doubled but too few to call
    sub = str(uuid.uuid4())
    await _grant(db, sub, "BR")
    out = await monitor_router.get_disease_trends(user=_officer(sub), db=db, district=None)
    by_code = {t.icd_code: t for t in out.trends}
    assert (by_code["A09"].this_week, by_code["A09"].spike) == ("24", True)
    assert (by_code["J18"].this_week, by_code["J18"].last_week) == ("<5", "12")
    assert by_code["B54"].spike is False
    assert out.week_ending == "2026-10-10"


async def test_trends_stay_inside_the_grant(db):
    patna = await _facility(db, district="Patna")
    gaya = await _facility(db, district="Gaya")
    await _counts(db, patna, "A09", this_week=10, last_week=0)
    await _counts(db, gaya, "A01", this_week=40, last_week=0)
    sub = str(uuid.uuid4())
    await _grant(db, sub, "BR", "Patna")
    codes = {t.icd_code for t in (await monitor_router.get_disease_trends(user=_officer(sub), db=db, district=None)).trends}
    assert "A09" in codes and "A01" not in codes


async def test_a_case_is_a_distinct_patient_with_a_non_differential_diagnosis(db):
    facility = await _facility(db)
    fid, user = facility.id, uuid.uuid4()
    await db.execute(sa.text("INSERT INTO users (id, keycloak_sub, username, full_name, facility_id) "
                             "VALUES (:u, :s, :n, 'Doctor', :f)"),
                     {"u": user, "s": str(uuid.uuid4()), "n": f"d{uuid.uuid4().hex[:8]}", "f": fid})
    async def encounter(patient, at):
        visit, enc = uuid.uuid4(), uuid.uuid4()
        await db.execute(sa.text("INSERT INTO visits (id, visit_number, patient_id, facility_id, visit_type, "
                                 "visit_date, created_by) VALUES (:id, :n, :p, :f, 'opd', :d, :u)"),
                         {"id": visit, "n": f"V-{uuid.uuid4().hex[:10]}", "p": patient, "f": fid, "d": at, "u": user})
        await db.execute(sa.text("INSERT INTO encounters (id, visit_id, facility_id, provider_user_id, created_by) "
                                 "VALUES (:e, :v, :f, :u, :u)"), {"e": enc, "v": visit, "f": fid, "u": user})
        return enc
    async def diagnose(enc, code, kind, at):
        await db.execute(sa.text("INSERT INTO diagnoses (id, encounter_id, facility_id, icd_code, icd_version, "
                                 "diagnosis_text, diagnosis_type, created_by, created_at) "
                                 "VALUES (:id, :e, :f, :c, 'icd10', 'free text', :t, :u, :at)"),
                         {"id": uuid.uuid4(), "e": enc, "f": fid, "c": code, "t": kind, "u": user, "at": at})
    patients = []
    for i in range(3):
        pid = uuid.uuid4()
        patients.append(pid)
        await db.execute(sa.text("INSERT INTO patients (id, full_name, sex, identity_path, facility_id, created_by, "
                                 "age_years, uhid) VALUES (:p, :n, 'other', 'demographics_only', :f, :u, 30, :h)"),
                         {"p": pid, "n": f"Trend {i}", "f": fid, "u": user, "h": f"IN-BR-{uuid.uuid4().hex[:10]}"})
    today = NOW - timedelta(hours=1)
    first = await encounter(patients[0], today)
    again = await encounter(patients[0], today)                      # same patient twice
    await diagnose(first, "a09", "final", today)                     # code normalised
    await diagnose(again, "A09", "provisional", today)
    await diagnose(await encounter(patients[1], today), "A09", "final", today)
    await diagnose(await encounter(patients[2], today), "A09", "differential", today)   # not a case
    yesterday = NOW - timedelta(days=1)
    await diagnose(await encounter(patients[2], yesterday), "J18", "final", yesterday)
    await db.flush()

    await service.capture_facility(db, facility, now=NOW)
    await db.flush()
    rows = (await db.execute(sa.select(DiagnosisDailyCount).where(DiagnosisDailyCount.facility_id == fid))).scalars().all()
    got = {(r.day.isoformat(), r.icd_code): r.patients for r in rows}
    assert got == {("2026-10-10", "A09"): 2, ("2026-10-09", "J18"): 1}
    # A second capture replaces, never adds.
    await service.capture_facility(db, facility, now=NOW)
    await db.flush()
    again_rows = (await db.execute(sa.select(DiagnosisDailyCount).where(DiagnosisDailyCount.facility_id == fid))).scalars().all()
    assert len(again_rows) == 2


# ---------------------------------------------------------------- staff and cover


async def test_rostered_staff_with_waiting_patients_and_no_activity_turn_the_row_amber(db):
    facility = await _facility(db)
    fid, dept = facility.id, uuid.uuid4()
    await db.execute(sa.text("INSERT INTO departments (id, name, code, facility_id) VALUES (:d, 'Medicine', :c, :f)"),
                     {"d": dept, "c": f"MED{uuid.uuid4().hex[:4]}", "f": fid})
    doctors = {}
    for name in ("Dr Active", "Dr Quiet"):
        doctors[name] = uuid.uuid4()
        await db.execute(sa.text("INSERT INTO users (id, keycloak_sub, username, full_name, designation, facility_id) "
                                 "VALUES (:u, :s, :n, :full, 'Medical Officer', :f)"),
                         {"u": doctors[name], "s": str(uuid.uuid4()), "n": f"d{uuid.uuid4().hex[:8]}", "full": name, "f": fid})
        await db.execute(sa.text("INSERT INTO rosters (id, staff_user_id, department_id, shift, roster_date) "
                                 "VALUES (:r, :u, :d, 'morning', :day)"),
                         {"r": uuid.uuid4(), "u": doctors[name], "d": dept, "day": date(2026, 10, 10)})
    # Dr Active did something this morning; Dr Quiet has a queue and nothing else.
    await db.execute(sa.text("INSERT INTO audit_logs (id, created_at, facility_id, user_id, action, resource_type) "
                             "VALUES (:id, :at, :f, :u, 'read', 'patients')"),
                     {"id": uuid.uuid4(), "at": NOW - timedelta(hours=2), "f": fid, "u": doctors["Dr Active"]})
    patient = uuid.uuid4()
    await db.execute(sa.text("INSERT INTO patients (id, full_name, sex, identity_path, facility_id, created_by, age_years, uhid) "
                             "VALUES (:p, 'Waiting Patient', 'other', 'demographics_only', :f, :u, 30, :h)"),
                     {"p": patient, "f": fid, "u": doctors["Dr Active"], "h": f"IN-BR-{uuid.uuid4().hex[:10]}"})
    queue = uuid.uuid4()
    await db.execute(sa.text("INSERT INTO queues (id, facility_id, department_id, doctor_user_id, service_date) "
                             "VALUES (:q, :f, :d, :u, :day)"),
                     {"q": queue, "f": fid, "d": dept, "u": doctors["Dr Quiet"], "day": date(2026, 10, 10)})
    for seq in (1, 2):
        visit = uuid.uuid4()
        await db.execute(sa.text("INSERT INTO visits (id, visit_number, patient_id, facility_id, visit_type, visit_date, created_by) "
                                 "VALUES (:v, :n, :p, :f, 'opd', :at, :u)"),
                         {"v": visit, "n": f"V-{uuid.uuid4().hex[:10]}", "p": patient, "f": fid, "at": NOW, "u": doctors["Dr Active"]})
        await db.execute(sa.text("INSERT INTO queue_tokens (id, facility_id, queue_id, visit_id, sequence, token_display, initial_priority) "
                                 "VALUES (:t, :f, :q, :v, :s, :d, 'normal')"),
                         {"t": uuid.uuid4(), "f": fid, "q": queue, "v": visit, "s": seq, "d": f"MED-{seq:03d}"})
    await db.flush()

    pulse = await service.capture_facility(db, facility, now=NOW)
    staff = {s["name"]: s for s in pulse.detail["staff"]}
    assert staff["Dr Active"]["active_today"] is True and staff["Dr Active"]["waiting"] == 0
    assert staff["Dr Quiet"]["active_today"] is False and staff["Dr Quiet"]["waiting"] == 2
    assert staff["Dr Quiet"]["department"] == "Medicine" and staff["Dr Quiet"]["shift"] == "morning"
    colour, reasons = service.status_of(pulse, now=NOW)
    assert colour == "amber"
    assert "2 patients waiting for 1 rostered staff with no activity yet" in reasons
# ---------------------------------------------------------------- session audit for officers


from types import SimpleNamespace  # noqa: E402

from app.audit import router as audit_router  # noqa: E402

_REQUEST = SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"))


async def test_an_officer_login_is_logged_without_a_facility_audit_row(db):
    sub = str(uuid.uuid4())
    before = (await db.execute(sa.text("SELECT count(*) FROM audit_logs"))).scalar_one()
    out = await audit_router.record_login(_REQUEST, jwt_user=_officer(sub), db=db)
    assert out == {"recorded": "login", "where": "application_log"}
    assert (await db.execute(sa.text("SELECT count(*) FROM audit_logs"))).scalar_one() == before


async def test_a_facility_users_login_still_writes_the_audit_row(db):
    facility = await _facility(db)
    sub = str(uuid.uuid4())
    await db.execute(sa.text("INSERT INTO users (id, keycloak_sub, username, full_name, facility_id) "
                             "VALUES (:u, :s, :n, 'Desk', :f)"),
                     {"u": uuid.uuid4(), "s": sub, "n": f"r{uuid.uuid4().hex[:8]}", "f": facility.id})
    await db.flush()
    out = await audit_router.record_login(
        _REQUEST, jwt_user=AuthUser(sub=sub, username="desk", roles=["receptionist"]), db=db
    )
    assert out == {"recorded": "login"}
    rows = (await db.execute(sa.text("SELECT count(*) FROM audit_logs WHERE facility_id = :f"), {"f": facility.id})).scalar_one()
    assert rows == 1


async def test_an_unprovisioned_non_officer_is_still_refused(db):
    with pytest.raises(HTTPException) as refused:
        await audit_router.record_login(
            _REQUEST, jwt_user=AuthUser(sub=str(uuid.uuid4()), username="x", roles=["doctor"]), db=db
        )
    assert refused.value.status_code == 403

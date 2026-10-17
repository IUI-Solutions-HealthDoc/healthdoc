"""Maternal and child health: record only. A pregnancy, its ANC visits and its
delivery are stored as clinicians record them; nothing is scheduled or inferred."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi import HTTPException

from app.auth.deps import DbUser
from app.mch import router as mch
from app.monitor import service as monitor
from app.users.models import Facility

pytestmark = pytest.mark.asyncio


async def _world(db):
    fid, other_fid, mother = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    nurse_id, receptionist_id, other_nurse_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    run = db.execute
    for f in (fid, other_fid):
        await run(sa.text("INSERT INTO facilities (id, code, name, state_code, district) VALUES (:id, :c, 'MCH Hospital', 'BR', 'Patna')"),
                  {"id": f, "c": f"M{uuid.uuid4().hex[:6].upper()}"})
    for uid, f in ((nurse_id, fid), (receptionist_id, fid), (other_nurse_id, other_fid)):
        await run(sa.text("INSERT INTO users (id, keycloak_sub, username, full_name, facility_id, is_active) "
                          "VALUES (:u, :s, :n, 'Staff', :f, true)"),
                  {"u": uid, "s": str(uuid.uuid4()), "n": f"s{uuid.uuid4().hex[:8]}", "f": f})
    await run(sa.text("INSERT INTO patients (id, full_name, sex, identity_path, facility_id, created_by, age_years, uhid) "
                      "VALUES (:p, 'Expectant Mother', 'female', 'demographics_only', :f, :u, 26, :h)"),
              {"p": mother, "f": fid, "u": nurse_id, "h": f"IN-BR-{uuid.uuid4().hex[:10]}"})
    await db.flush()

    def user(uid, f, roles):
        return DbUser(id=uid, keycloak_sub=str(uid), username="u", facility_id=f, roles=roles)

    return (mother, fid, user(nurse_id, fid, ["nurse"]), user(receptionist_id, fid, ["admin"]),
            user(other_nurse_id, other_fid, ["nurse"]))


def _key():
    return f"k-{uuid.uuid4().hex}"


async def test_a_pregnancy_is_followed_to_delivery_and_counted_without_names(db):
    mother, fid, nurse, _admin, _other = await _world(db)
    # Relative to today: the plausibility checks compare the LMP with the visit
    # and delivery dates, so fixed dates would age out of range.
    lmp = datetime.now(UTC).date() - timedelta(days=230)
    edd = lmp + timedelta(days=282)
    preg = await mch.register_pregnancy(
        mch.PregnancyCreate(patient_id=mother, lmp_date=lmp, edd=edd, gravida=2, para=1),
        current_user=nurse, db=db, idempotency_key=_key(),
    )
    assert (preg.status, preg.edd) == ("active", edd)  # stored as entered, not computed
    with pytest.raises(HTTPException) as again:
        await mch.register_pregnancy(mch.PregnancyCreate(patient_id=mother), current_user=nurse, db=db, idempotency_key=_key())
    assert again.value.detail["code"] == "pregnancy_already_active"

    today = datetime.now(UTC).date()
    preg = await mch.record_anc_visit(
        preg.id, mch.AncVisitCreate(visit_date=today, gestation_weeks=31, weight_kg=Decimal("62.5"), bp_systolic=150,
                                    bp_diastolic=100, hemoglobin_g_dl=Decimal("8.9"), urine_albumin="+"),
        current_user=nurse, db=db, idempotency_key=_key(),
    )
    assert len(preg.anc_visits) == 1 and preg.high_risk is False  # nothing is inferred from the readings
    with pytest.raises(HTTPException) as no_reason:
        await mch.flag_risk(preg.id, mch.RiskFlag(high_risk=True), current_user=nurse, db=db, idempotency_key=_key())
    assert no_reason.value.detail["code"] == "risk_reason_required"
    preg = await mch.flag_risk(preg.id, mch.RiskFlag(high_risk=True, reason="Pre-eclampsia suspected"),
                               current_user=nurse, db=db, idempotency_key=_key())
    assert preg.high_risk is True

    facility = await db.get(Facility, fid)
    pulse = await monitor.capture_facility(db, facility, now=datetime.now(UTC))
    assert pulse.detail["mch"]["active_pregnancies"] == 1 and pulse.detail["mch"]["high_risk"] == 1
    assert "Expectant Mother" not in str(pulse.detail)

    preg = await mch.record_delivery(
        preg.id,
        mch.DeliveryCreate(delivered_at=datetime.now(UTC) - timedelta(minutes=5), mode="caesarean",
                           newborns=[mch.NewbornIn(outcome="live_birth", sex="female", birth_weight_g=2600)]),
        current_user=nurse, db=db, idempotency_key=_key(),
    )
    assert preg.status == "delivered" and preg.delivery.newborns[0].birth_weight_g == 2600
    with pytest.raises(HTTPException) as closed:
        await mch.record_anc_visit(preg.id, mch.AncVisitCreate(visit_date=today), current_user=nurse, db=db,
                                   idempotency_key=_key())
    assert closed.value.detail["code"] == "pregnancy_closed"


async def test_a_retry_replays_and_a_reading_must_be_whole(db):
    mother, _fid, nurse, _admin, _other = await _world(db)
    key = _key()
    first = await mch.register_pregnancy(mch.PregnancyCreate(patient_id=mother), current_user=nurse, db=db, idempotency_key=key)
    again = await mch.register_pregnancy(mch.PregnancyCreate(patient_id=mother), current_user=nurse, db=db, idempotency_key=key)
    assert first.id == again.id
    with pytest.raises(HTTPException) as half:
        await mch.record_anc_visit(first.id, mch.AncVisitCreate(visit_date=datetime.now(UTC).date(), bp_systolic=120),
                                   current_user=nurse, db=db, idempotency_key=_key())
    assert half.value.detail["code"] == "bp_incomplete"
    with pytest.raises(HTTPException) as future:
        await mch.record_anc_visit(first.id, mch.AncVisitCreate(visit_date=datetime.now(UTC).date() + timedelta(days=2)),
                                   current_user=nurse, db=db, idempotency_key=_key())
    assert future.value.detail["code"] == "visit_in_future"


async def test_only_doctors_and_nurses_write_and_other_facilities_cannot_see(db):
    mother, _fid, nurse, admin, other_nurse = await _world(db)
    with pytest.raises(HTTPException) as refused:
        await mch.register_pregnancy(mch.PregnancyCreate(patient_id=mother), current_user=admin, db=db, idempotency_key=_key())
    assert refused.value.status_code == 403
    preg = await mch.register_pregnancy(mch.PregnancyCreate(patient_id=mother), current_user=nurse, db=db, idempotency_key=_key())
    assert [p.id for p in await mch.list_pregnancies(mother, current_user=admin, db=db)] == [preg.id]
    with pytest.raises(HTTPException) as hidden:
        await mch.record_anc_visit(preg.id, mch.AncVisitCreate(visit_date=datetime.now(UTC).date()),
                                   current_user=other_nurse, db=db, idempotency_key=_key())
    assert hidden.value.status_code == 404


async def test_ending_a_pregnancy_needs_a_reason_and_frees_the_patient(db):
    mother, _fid, nurse, _admin, _other = await _world(db)
    preg = await mch.register_pregnancy(mch.PregnancyCreate(patient_id=mother), current_user=nurse, db=db, idempotency_key=_key())
    ended = await mch.end_pregnancy(preg.id, mch.PregnancyEnd(reason="Transferred to district hospital"),
                                    current_user=nurse, db=db, idempotency_key=_key())
    assert ended.status == "ended"
    second = await mch.register_pregnancy(mch.PregnancyCreate(patient_id=mother), current_user=nurse, db=db,
                                          idempotency_key=_key())
    assert second.status == "active"



async def _patient(db, fid, created_by, *, sex="female", age=26):
    pid = uuid.uuid4()
    await db.execute(
        sa.text("INSERT INTO patients (id, full_name, sex, identity_path, facility_id, created_by, age_years, uhid) "
                "VALUES (:p, 'Another Patient', :s, 'demographics_only', :f, :u, :a, :h)"),
        {"p": pid, "s": sex, "f": fid, "u": created_by, "a": age, "h": f"IN-BR-{uuid.uuid4().hex[:10]}"},
    )
    await db.flush()
    return pid


async def _refusal(call):
    with pytest.raises(HTTPException) as exc:
        await call
    assert isinstance(exc.value.detail, dict), exc.value.detail
    return exc.value.detail["code"]


# QA 16 Oct 2026: each of these saved. A refused clinical write rolls the
# session back, so each case sets up its own world.
@pytest.mark.parametrize(
    "sex,age,kwargs,code",
    [
        ("female", 4, {"lmp": 40}, "pregnancy_age"),
        ("male", 30, {"lmp": 40}, "pregnancy_sex"),
        ("female", 26, {"lmp": 46, "edd": -85}, "edd_inconsistent"),
        ("female", 26, {"gravida": 1, "para": 3}, "para_exceeds_gravida"),
    ],
)
async def test_an_impossible_pregnancy_is_refused(db, sex, age, kwargs, code):
    _mother, fid, nurse, _admin, _other = await _world(db)
    patient = await _patient(db, fid, nurse.id, sex=sex, age=age)
    today = datetime.now(UTC).date()
    lmp = today - timedelta(days=kwargs["lmp"]) if "lmp" in kwargs else None
    edd = lmp + timedelta(days=kwargs["edd"]) if "edd" in kwargs else None
    payload = mch.PregnancyCreate(
        patient_id=patient, lmp_date=lmp, edd=edd, gravida=kwargs.get("gravida"), para=kwargs.get("para"),
    )
    assert await _refusal(mch.register_pregnancy(payload, current_user=nurse, db=db, idempotency_key=_key())) == code


@pytest.mark.parametrize(
    "visit,code",
    [
        ({"gestation_weeks": 40}, "gestation_inconsistent"),
        ({"bp_systolic": 60, "bp_diastolic": 120}, "bp_inverted"),
        ("delivery", "delivery_too_early"),
    ],
)
async def test_an_impossible_visit_or_delivery_is_refused(db, visit, code):
    mother, _fid, nurse, _admin, _other = await _world(db)
    today = datetime.now(UTC).date()
    preg = await mch.register_pregnancy(
        mch.PregnancyCreate(patient_id=mother, lmp_date=today - timedelta(days=46), gravida=1, para=0),
        current_user=nurse, db=db, idempotency_key=_key(),
    )
    if visit == "delivery":
        call = mch.record_delivery(
            preg.id,
            mch.DeliveryCreate(delivered_at=datetime.now(UTC) - timedelta(minutes=5), mode="normal",
                               newborns=[mch.NewbornIn(outcome="live_birth", sex="male", birth_weight_g=2900)]),
            current_user=nurse, db=db, idempotency_key=_key(),
        )
    else:
        call = mch.record_anc_visit(
            preg.id, mch.AncVisitCreate(visit_date=today, **visit), current_user=nurse, db=db, idempotency_key=_key(),
        )
    assert await _refusal(call) == code


async def test_a_consistent_early_visit_is_recorded(db):
    mother, _fid, nurse, _admin, _other = await _world(db)
    today = datetime.now(UTC).date()
    preg = await mch.register_pregnancy(
        mch.PregnancyCreate(patient_id=mother, lmp_date=today - timedelta(days=46), gravida=1, para=0),
        current_user=nurse, db=db, idempotency_key=_key(),
    )
    preg = await mch.record_anc_visit(
        preg.id, mch.AncVisitCreate(visit_date=today, gestation_weeks=7, bp_systolic=118, bp_diastolic=76),
        current_user=nurse, db=db, idempotency_key=_key(),
    )
    assert len(preg.anc_visits) == 1

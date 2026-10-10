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
    preg = await mch.register_pregnancy(
        mch.PregnancyCreate(patient_id=mother, lmp_date=date(2026, 3, 1), edd=date(2026, 12, 6), gravida=2, para=1),
        current_user=nurse, db=db, idempotency_key=_key(),
    )
    assert (preg.status, preg.edd) == ("active", date(2026, 12, 6))  # stored as entered, not computed
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

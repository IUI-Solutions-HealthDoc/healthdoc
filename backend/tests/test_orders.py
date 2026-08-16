"""backend/tests/test_orders.py -- #181: order creation, gapless sequence, encounter-not-found."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.opd.models import Visit, Encounter
from app.patients.models import Patient
from app.orders import service
from app.orders.schemas import OrderCreate


@pytest.fixture
async def encounter(db, seed):
    dept, room, doctor = seed
    patient = Patient(id=uuid.uuid4(), uhid=f"UH{uuid.uuid4().hex[:8]}", facility_id=dept.facility_id,
                       full_name="Test Patient", sex="female", age_years=30,
                       identity_path="demographics_only", created_by=doctor.id)
    db.add(patient)
    await db.flush()
    v = Visit(id=uuid.uuid4(), visit_number=f"V{uuid.uuid4().hex[:8]}", patient_id=patient.id,
              facility_id=dept.facility_id, department_id=dept.id, visit_type="opd",
              visit_date=datetime.now(timezone.utc), created_by=doctor.id)
    db.add(v)
    await db.flush()
    e = Encounter(id=uuid.uuid4(), visit_id=v.id, facility_id=dept.facility_id,
                  provider_user_id=doctor.id, created_by=doctor.id, note_status="pending", row_version=1)
    db.add(e)
    await db.flush()
    return e, patient, doctor


async def test_create_order(db, encounter):
    e, patient, doctor = encounter
    order = await service.create_order(
        db, OrderCreate(encounter_id=e.id, patient_id=patient.id, created_by=doctor.id, order_type="lab"),
    )

    assert order.order_number.startswith("ORD-")
    assert order.order_number.split("-")[2].isdigit() and len(order.order_number.split("-")[2]) == 6
    assert order.status == "placed"
    assert order.priority == "routine"
    assert order.facility_id == e.facility_id


async def test_order_sequence_is_gapless_per_day(db, encounter):
    e, patient, doctor = encounter
    o1 = await service.create_order(
        db, OrderCreate(encounter_id=e.id, patient_id=patient.id, created_by=doctor.id, order_type="lab"),
    )
    o2 = await service.create_order(
        db, OrderCreate(encounter_id=e.id, patient_id=patient.id, created_by=doctor.id, order_type="radiology"),
    )

    seq1 = int(o1.order_number.split("-")[2])
    seq2 = int(o2.order_number.split("-")[2])
    assert seq2 == seq1 + 1
    assert o1.order_number != o2.order_number


async def test_create_order_encounter_not_found(db, seed):
    dept, room, doctor = seed
    with pytest.raises(service.EncounterNotFound):
        await service.create_order(
            db, OrderCreate(encounter_id=uuid.uuid4(), patient_id=uuid.uuid4(),
                             created_by=doctor.id, order_type="pharmacy"),
        )


async def test_business_date_uses_encounters_own_facility_timezone(db, seed):
    """Regression test for #362: business_date used to come from
    whichever facility happened to be passed in as facility_timezone
    (in production, the CALLER's facility -- see the router's old
    code), while Order.facility_id and the order_number_counters row
    both used encounter.facility_id. On a same-facility request the two
    always matched by coincidence; this seeds a facility in a
    different timezone from the encounter's own and confirms
    create_order() now resolves the timezone from encounter.facility_id
    itself -- there is only one facility in play, ever."""
    from app.users.models import Facility
    dept, room, doctor = seed

    other_facility = Facility(
        id=uuid.uuid4(), code="OTH01", name="Other Facility", state_code="TS",
        timezone="America/New_York",
    )
    db.add(other_facility)
    await db.flush()

    patient = Patient(id=uuid.uuid4(), uhid=f"UH{uuid.uuid4().hex[:8]}", facility_id=dept.facility_id,
                       full_name="Test Patient", sex="female", age_years=30,
                       identity_path="demographics_only", created_by=doctor.id)
    db.add(patient)
    await db.flush()
    visit = Visit(id=uuid.uuid4(), visit_number=f"V{uuid.uuid4().hex[:8]}", patient_id=patient.id,
                  facility_id=dept.facility_id, department_id=dept.id, visit_type="opd",
                  visit_date=datetime.now(timezone.utc), created_by=doctor.id)
    db.add(visit)
    await db.flush()
    # The encounter belongs to other_facility (America/New_York), not
    # dept.facility_id (the "caller's" facility in the old buggy code).
    encounter = Encounter(id=uuid.uuid4(), visit_id=visit.id, facility_id=other_facility.id,
                          provider_user_id=doctor.id, created_by=doctor.id,
                          note_status="pending", row_version=1)
    db.add(encounter)
    await db.flush()

    order = await service.create_order(
        db, OrderCreate(encounter_id=encounter.id, patient_id=patient.id,
                         created_by=doctor.id, order_type="lab"),
    )

    # facility_id and the business-date-derived order_number must both
    # reflect other_facility -- never dept.facility_id.
    assert order.facility_id == other_facility.id
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo
    expected_date = dt.now(ZoneInfo("America/New_York")).date()
    assert order.order_number == f"ORD-{expected_date:%Y%m%d}-000001"

"""Kitchen, laundry and housekeeping (0104).

The properties that matter on a ward: a discharged patient's bed is not offered
to the next patient until it is recorded clean; a nil-by-mouth patient is never
recorded as fed; one diet is in force at a time and discharge stops it; linen
counted out is counted back, with what went missing visible; and another
facility's records do not exist for the caller.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.admissions import service as admissions
from app.admissions.models import Bed, Ward
from app.dietary import router as dietary
from app.dietary.models import DietOrder
from app.dietary.service import ward_today
from app.housekeeping import router as housekeeping
from app.housekeeping.models import HousekeepingTask
from app.laundry import router as laundry
from app.users.models import Facility, User
from app.wards import router as wards
from tests.admissions.conftest import seed_bed, seed_patient, seed_visit

pytestmark = pytest.mark.asyncio


class _Caller:
    def __init__(self, facility_id, user_id, roles):
        self.facility_id, self.id, self.roles = facility_id, user_id, roles


def _key() -> str:
    return str(uuid.uuid4())


async def _admitted(db, seed, *, bed_number="1"):
    dept, _room, doctor = seed
    # is_active explicit: the SQLite fixture stores the server default 'true' as text.
    ward = Ward(id=uuid.uuid4(), name=f"Ward {uuid.uuid4().hex[:4]}", facility_id=dept.facility_id, is_active=True)
    db.add(ward)
    await db.flush()
    bed = await seed_bed(db, ward_id=ward.id, bed_number=bed_number)
    patient = await seed_patient(db, facility_id=dept.facility_id, created_by=doctor.id)
    visit = await seed_visit(db, facility_id=dept.facility_id, patient_id=patient.id, created_by=doctor.id)
    admission = await admissions.admit_patient(
        db, visit_id=visit.id, ward_id=ward.id, bed_id=bed.id, created_by=doctor.id,
        admitted_at=datetime.now(UTC) - timedelta(days=1),
    )
    caller = _Caller(dept.facility_id, doctor.id, ["doctor", "nurse", "admin"])
    return caller, ward, bed, admission


async def _other_facility_caller(db):
    facility = Facility(id=uuid.uuid4(), code=f"O{uuid.uuid4().hex[:5]}", name="Other", state_code="BR")
    db.add(facility)
    await db.flush()
    user = User(id=uuid.uuid4(), facility_id=facility.id, keycloak_sub=str(uuid.uuid4()),
                username=f"o{uuid.uuid4().hex[:6]}", full_name="Other nurse", is_active=True)
    db.add(user)
    await db.flush()
    return _Caller(facility.id, user.id, ["nurse", "admin"])


async def _discharge(db, admission, caller):
    return await admissions.discharge_patient(
        db, admission=admission, discharge_type="discharged", created_by=caller.id,
        acknowledge_incomplete_checklist=True,
    )


async def _order(db, caller, admission, diet_type="diabetic", **fields):
    return await dietary.order_diet(
        dietary.DietOrderCreate(admission_id=admission.id, diet_type=diet_type, **fields),
        current_db_user=caller, idempotency_key=_key(), db=db,
    )


async def _meal(db, caller, admission, meal="lunch", status="served", notes=None, day=None):
    return await dietary.record_meal(
        dietary.MealCreate(admission_id=admission.id, service_date=day or ward_today(), meal=meal, status=status, notes=notes),
        current_db_user=caller, idempotency_key=_key(), db=db,
    )


# ---------------------------------------------------------------- bed turnover


async def test_discharge_puts_the_bed_in_cleaning_and_raises_one_urgent_turnover(db, seed):
    caller, ward, bed, admission = await _admitted(db, seed)
    await _discharge(db, admission, caller)
    await db.refresh(bed)
    assert bed.status == "cleaning"
    tasks = (await db.execute(select(HousekeepingTask).where(HousekeepingTask.bed_id == bed.id))).scalars().all()
    assert [(t.task_type, t.source, t.priority, t.status, t.admission_id) for t in tasks] == [
        ("bed_turnover", "discharge", "urgent", "pending", admission.id)
    ]
    open_tasks = await housekeeping.list_tasks(current_db_user=caller, db=db, state="open", ward_id=None)
    assert [(t.bed_number, t.ward_name) for t in open_tasks] == [(bed.bed_number, ward.name)]


async def test_a_bed_waiting_for_cleaning_cannot_take_the_next_patient(db, seed):
    caller, ward, bed, admission = await _admitted(db, seed)
    await _discharge(db, admission, caller)
    dept, _room, doctor = seed
    patient = await seed_patient(db, facility_id=dept.facility_id, created_by=doctor.id)
    visit = await seed_visit(db, facility_id=dept.facility_id, patient_id=patient.id, created_by=doctor.id)
    with pytest.raises(admissions.BedNotAvailable):
        await admissions.admit_patient(db, visit_id=visit.id, ward_id=ward.id, bed_id=bed.id, created_by=doctor.id)


async def test_a_transfer_leaves_the_old_bed_for_housekeeping(db, seed):
    caller, ward, bed, admission = await _admitted(db, seed)
    other_bed = await seed_bed(db, ward_id=ward.id, bed_number="2")
    await admissions.transfer_patient(db, admission=admission, to_ward_id=ward.id, to_bed_id=other_bed.id, moved_by=caller.id)
    await db.refresh(bed)
    assert bed.status == "cleaning"
    task = (await db.execute(select(HousekeepingTask).where(HousekeepingTask.bed_id == bed.id))).scalar_one()
    assert (task.source, task.task_type) == ("transfer", "bed_turnover")


async def test_a_turnover_completes_only_when_the_bed_is_actually_ready_and_then_frees_it(db, seed):
    caller, ward, bed, admission = await _admitted(db, seed)
    await _discharge(db, admission, caller)
    task = (await db.execute(select(HousekeepingTask).where(HousekeepingTask.bed_id == bed.id))).scalar_one()

    with pytest.raises(HTTPException) as refused:
        await housekeeping.complete_task(
            task.id, housekeeping.TaskComplete(linen_changed=True, surfaces_disinfected=True),
            current_db_user=caller, idempotency_key=_key(), db=db,
        )
    assert refused.value.detail["code"] == "turnover_incomplete"
    await db.refresh(bed)
    assert bed.status == "cleaning"

    started = await housekeeping.start_task(
        task.id, housekeeping.TaskStart(assigned_to_name="Sunita"), current_db_user=caller, idempotency_key=_key(), db=db,
    )
    assert (started.status, started.assigned_to_name) == ("in_progress", "Sunita")
    done = await housekeeping.complete_task(
        task.id,
        housekeeping.TaskComplete(
            linen_changed=True, mattress_disinfected=True, surfaces_disinfected=True, waste_removed=True,
            linen_items=[housekeeping.LinenLine(item_type="bed_sheet", quantity=2),
                         housekeeping.LinenLine(item_type="pillow_cover", quantity=1)],
        ),
        current_db_user=caller, idempotency_key=_key(), db=db,
    )
    assert done.status == "done" and done.linen_batch_id is not None
    await db.refresh(bed)
    assert bed.status == "vacant"
    batches = await laundry.list_batches(current_db_user=caller, db=db, status=None, open_only=True)
    assert [(b.id, b.bed_number, sorted((i.item_type, i.quantity) for i in b.items)) for b in batches] == [
        (done.linen_batch_id, bed.bed_number, [("bed_sheet", 2), ("pillow_cover", 1)])
    ]


async def test_cancelling_a_turnover_needs_a_reason_and_frees_the_bed(db, seed):
    caller, _ward, bed, admission = await _admitted(db, seed)
    await _discharge(db, admission, caller)
    task = (await db.execute(select(HousekeepingTask).where(HousekeepingTask.bed_id == bed.id))).scalar_one()
    cancelled = await housekeeping.cancel_task(
        task.id, housekeeping.TaskCancel(reason="Cleaned before the discharge was recorded"),
        current_db_user=caller, idempotency_key=_key(), db=db,
    )
    assert cancelled.status == "cancelled"
    await db.refresh(bed)
    assert bed.status == "vacant"
    with pytest.raises(HTTPException) as refused:
        await housekeeping.start_task(task.id, housekeeping.TaskStart(), current_db_user=caller, idempotency_key=_key(), db=db)
    assert refused.value.detail["code"] == "task_closed"


async def test_an_admin_freeing_a_cleaning_bed_closes_its_turnover_on_the_record(db, seed):
    caller, _ward, bed, admission = await _admitted(db, seed)
    await _discharge(db, admission, caller)
    out = await wards.change_bed_status(
        bed.id, wards.BedStatusChange(status="vacant", reason="Cleaned, task not recorded"), current_db_user=caller, db=db,
    )
    assert out.status == "vacant"
    task = (await db.execute(select(HousekeepingTask).where(HousekeepingTask.bed_id == bed.id))).scalar_one()
    assert task.status == "cancelled" and "Cleaned, task not recorded" in task.cancel_reason


async def test_a_turnover_cannot_be_raised_by_hand_but_a_spill_can(db, seed):
    caller, ward, bed, _admission = await _admitted(db, seed)
    with pytest.raises(HTTPException) as refused:
        await housekeeping.raise_task(
            housekeeping.TaskCreate(ward_id=ward.id, bed_id=bed.id, task_type="bed_turnover"),
            current_db_user=caller, idempotency_key=_key(), db=db,
        )
    assert refused.value.detail["code"] == "turnover_is_automatic"
    spill = await housekeeping.raise_task(
        housekeeping.TaskCreate(ward_id=ward.id, bed_id=bed.id, task_type="spill", priority="urgent", notes="Near bed 1"),
        current_db_user=caller, idempotency_key=_key(), db=db,
    )
    # A spill clean does not touch the bed's status: the patient is still in it.
    done = await housekeeping.complete_task(
        spill.id, housekeeping.TaskComplete(surfaces_disinfected=True), current_db_user=caller, idempotency_key=_key(), db=db,
    )
    assert done.status == "done"
    await db.refresh(bed)
    assert bed.status == "occupied"


async def test_another_facilitys_task_is_not_found(db, seed):
    caller, _ward, bed, admission = await _admitted(db, seed)
    await _discharge(db, admission, caller)
    task = (await db.execute(select(HousekeepingTask).where(HousekeepingTask.bed_id == bed.id))).scalar_one()
    other = await _other_facility_caller(db)
    with pytest.raises(HTTPException) as refused:
        await housekeeping.start_task(task.id, housekeeping.TaskStart(), current_db_user=other, idempotency_key=_key(), db=db)
    assert refused.value.status_code == 404
    assert await housekeeping.list_tasks(current_db_user=other, db=db, state="open", ward_id=None) == []


# ------------------------------------------------------------------- diet


async def test_one_diet_is_in_force_and_a_change_stops_the_old_one(db, seed):
    caller, _ward, _bed, admission = await _admitted(db, seed)
    first = await _order(db, caller, admission, instructions="No sugar")
    with pytest.raises(HTTPException) as refused:
        await _order(db, caller, admission, instructions="No sugar")
    assert refused.value.detail["code"] == "diet_unchanged"
    second = await _order(db, caller, admission, diet_type="soft")
    history = await dietary.diet_history(admission.id, current_db_user=caller, db=db)
    assert {(h.id, h.status) for h in history} == {(first.id, "stopped"), (second.id, "active")}


async def test_other_needs_instructions(db, seed):
    caller, _ward, _bed, admission = await _admitted(db, seed)
    with pytest.raises(HTTPException) as refused:
        await _order(db, caller, admission, diet_type="other")
    assert refused.value.detail["code"] == "instructions_required"


async def test_a_nil_by_mouth_patient_cannot_be_recorded_as_served(db, seed):
    caller, _ward, _bed, admission = await _admitted(db, seed)
    await _order(db, caller, admission, diet_type="npo", instructions="Surgery 9 am")
    with pytest.raises(HTTPException) as refused:
        await _meal(db, caller, admission, meal="breakfast", status="served")
    assert refused.value.detail["code"] == "patient_is_npo"
    held = await _meal(db, caller, admission, meal="breakfast", status="not_served", notes="NPO for surgery")
    assert held.status == "not_served"


async def test_a_meal_is_recorded_once_and_not_served_says_why(db, seed):
    caller, _ward, _bed, admission = await _admitted(db, seed)
    order = await _order(db, caller, admission)
    lunch = await _meal(db, caller, admission)
    assert lunch.diet_order_id == order.id
    with pytest.raises(HTTPException) as refused:
        await _meal(db, caller, admission, status="refused")
    assert refused.value.detail["code"] == "meal_already_recorded"
    with pytest.raises(HTTPException) as refused:
        await _meal(db, caller, admission, meal="dinner", status="not_served")
    assert refused.value.detail["code"] == "reason_required"
    with pytest.raises(HTTPException) as refused:
        await _meal(db, caller, admission, meal="dinner", day=ward_today() + timedelta(days=1))
    assert refused.value.detail["code"] == "meal_in_future"


async def test_the_kitchen_board_lists_every_admitted_patient_with_diet_and_meals(db, seed):
    caller, ward, bed, admission = await _admitted(db, seed)
    _c, _w, _b, no_order = await _admitted(db, seed, bed_number="7")
    await _order(db, caller, admission, diet_type="renal", food_allergies="Peanuts")
    await _meal(db, caller, admission, meal="breakfast")
    board = await dietary.kitchen_board(current_db_user=caller, db=db, service_date=None, ward_id=None)
    rows = {r.admission_id: r for r in board.rows}
    assert rows[admission.id].diet.diet_type == "renal" and rows[admission.id].diet.food_allergies == "Peanuts"
    assert [m.meal for m in rows[admission.id].meals] == ["breakfast"]
    assert rows[admission.id].bed_number == bed.bed_number and rows[admission.id].ward_name == ward.name
    # No order is listed, not hidden: it is what the kitchen has to chase.
    assert rows[no_order.id].diet is None


async def test_discharge_stops_the_diet_and_takes_the_patient_off_the_board(db, seed):
    caller, _ward, _bed, admission = await _admitted(db, seed)
    order = await _order(db, caller, admission)
    await _discharge(db, admission, caller)
    stopped = await db.get(DietOrder, order.id)
    assert (stopped.status, stopped.stop_reason) == ("stopped", "Patient discharged")
    board = await dietary.kitchen_board(current_db_user=caller, db=db, service_date=None, ward_id=None)
    assert admission.id not in {r.admission_id for r in board.rows}
    with pytest.raises(HTTPException) as refused:
        await _meal(db, caller, admission)
    assert refused.value.detail["code"] == "admission_not_active"


async def test_another_facilitys_admission_is_not_found_for_diet(db, seed):
    _caller, _ward, _bed, admission = await _admitted(db, seed)
    other = await _other_facility_caller(db)
    with pytest.raises(HTTPException) as refused:
        await _order(db, other, admission)
    assert refused.value.status_code == 404


async def test_a_repeated_diet_order_with_the_same_key_replays(db, seed):
    caller, _ward, _bed, admission = await _admitted(db, seed)
    payload = dietary.DietOrderCreate(admission_id=admission.id, diet_type="soft")
    first = await dietary.order_diet(payload, current_db_user=caller, idempotency_key="diet-1", db=db)
    again = await dietary.order_diet(payload, current_db_user=caller, idempotency_key="diet-1", db=db)
    assert first == again


# ---------------------------------------------------------------- laundry


async def _batch(db, caller, ward, **fields):
    payload = laundry.BatchCreate(
        ward_id=ward.id, items=[laundry.LinenLine(item_type="bed_sheet", quantity=10),
                                laundry.LinenLine(item_type="blanket", quantity=2)], **fields,
    )
    return await laundry.collect_linen(payload, current_db_user=caller, idempotency_key=_key(), db=db)


async def _advance(db, caller, batch_id, status, counts=None):
    return await laundry.advance_batch(
        batch_id, laundry.BatchAdvance(status=status, counts=counts), current_db_user=caller, idempotency_key=_key(), db=db,
    )


async def test_linen_moves_forward_one_step_and_is_counted_back(db, seed):
    caller, ward, _bed, _admission = await _admitted(db, seed)
    batch = await _batch(db, caller, ward, is_infected=True)
    assert (batch.status, batch.is_infected) == ("collected", True)
    with pytest.raises(HTTPException) as refused:
        await _advance(db, caller, batch.id, "ready")
    assert refused.value.detail["code"] == "wrong_step"
    await _advance(db, caller, batch.id, "washing")
    await _advance(db, caller, batch.id, "ready")
    with pytest.raises(HTTPException) as refused:
        await _advance(db, caller, batch.id, "returned", [laundry.ReturnCount(item_type="bed_sheet", returned=10)])
    assert refused.value.detail["code"] == "count_every_item"
    with pytest.raises(HTTPException) as refused:
        await _advance(db, caller, batch.id, "returned", [
            laundry.ReturnCount(item_type="bed_sheet", returned=10, condemned=1),
            laundry.ReturnCount(item_type="blanket", returned=2),
        ])
    assert refused.value.detail["code"] == "count_exceeds_sent"
    returned = await _advance(db, caller, batch.id, "returned", [
        laundry.ReturnCount(item_type="bed_sheet", returned=8, condemned=1),
        laundry.ReturnCount(item_type="blanket", returned=2),
    ])
    lines = {i.item_type: (i.returned_quantity, i.condemned_quantity, i.missing_quantity) for i in returned.items}
    assert lines == {"bed_sheet": (8, 1, 1), "blanket": (2, 0, 0)}
    history = await laundry.batch_history(batch.id, current_db_user=caller, db=db)
    assert [h.to_status for h in history] == ["collected", "washing", "ready", "returned"]
    with pytest.raises(HTTPException) as refused:
        await _advance(db, caller, batch.id, "washing")
    assert refused.value.detail["code"] == "batch_returned"


async def test_linen_needs_a_source_and_another_facilitys_batch_is_not_found(db, seed):
    caller, ward, _bed, _admission = await _admitted(db, seed)
    with pytest.raises(HTTPException) as refused:
        await laundry.collect_linen(
            laundry.BatchCreate(items=[laundry.LinenLine(item_type="towel", quantity=1)]),
            current_db_user=caller, idempotency_key=_key(), db=db,
        )
    assert refused.value.detail["code"] == "source_required"
    ot = await laundry.collect_linen(
        laundry.BatchCreate(source="OT 2", items=[laundry.LinenLine(item_type="ot_linen", quantity=4)]),
        current_db_user=caller, idempotency_key=_key(), db=db,
    )
    assert ot.source == "OT 2"
    batch = await _batch(db, caller, ward)
    other = await _other_facility_caller(db)
    with pytest.raises(HTTPException) as refused:
        await _advance(db, other, batch.id, "washing")
    assert refused.value.status_code == 404
    with pytest.raises(HTTPException) as refused:
        await laundry.collect_linen(
            laundry.BatchCreate(ward_id=ward.id, items=[laundry.LinenLine(item_type="towel", quantity=1)]),
            current_db_user=other, idempotency_key=_key(), db=db,
        )
    assert refused.value.status_code == 404


async def test_a_bed_from_another_ward_is_refused(db, seed):
    caller, ward, _bed, _admission = await _admitted(db, seed)
    _c, _other_ward, other_bed, _a = await _admitted(db, seed, bed_number="9")
    with pytest.raises(HTTPException) as refused:
        await laundry.collect_linen(
            laundry.BatchCreate(ward_id=ward.id, bed_id=other_bed.id, items=[laundry.LinenLine(item_type="towel", quantity=1)]),
            current_db_user=caller, idempotency_key=_key(), db=db,
        )
    assert refused.value.status_code == 404
    assert isinstance(other_bed, Bed)


async def test_ward_locations_list_places_without_patients(db, seed):
    caller, ward, bed, _admission = await _admitted(db, seed)
    locations = await wards.list_locations(current_db_user=caller, db=db)
    mine = next(loc for loc in locations if loc.ward_id == ward.id)
    assert [b.model_dump() for b in mine.beds] == [{"bed_id": bed.id, "bed_number": bed.bed_number, "status": "occupied"}]
    other = await _other_facility_caller(db)
    assert await wards.list_locations(current_db_user=other, db=db) == []

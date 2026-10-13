"""Equipment register: a status change is recorded with a reason and a name,
a retired machine stays retired, and another facility's machine is not found."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.equipment import router as equipment_router
from app.equipment.models import EquipmentStatusEvent
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


class _Caller:
    def __init__(self, facility_id, user_id, roles):
        self.facility_id, self.id, self.roles = facility_id, user_id, roles


async def _setup(db):
    facility = Facility(id=uuid.uuid4(), code=f"E{uuid.uuid4().hex[:5]}", name="Equipment Facility", state_code="BR")
    db.add(facility)
    await db.flush()
    users = {}
    for role in ("admin", "nurse"):
        users[role] = User(id=uuid.uuid4(), facility_id=facility.id, keycloak_sub=str(uuid.uuid4()),
                           username=f"{role}{uuid.uuid4().hex[:6]}", full_name=f"Test {role}", is_active=True)
        db.add(users[role])
    await db.flush()
    admin = _Caller(facility.id, users["admin"].id, ["admin"])
    nurse = _Caller(facility.id, users["nurse"].id, ["nurse"])
    return facility, admin, nurse


async def _register(db, admin, **fields):
    payload = equipment_router.EquipmentCreate(name="Ventilator ICU-1", category="life_support", is_critical=True, **fields)
    return await equipment_router.register_equipment(payload, current_db_user=admin, idempotency_key=str(uuid.uuid4()), db=db)


async def _status(db, caller, equipment_id, status, reason=None, key=None):
    return await equipment_router.change_equipment_status(
        equipment_id, equipment_router.StatusChange(status=status, reason=reason),
        current_db_user=caller, idempotency_key=key or str(uuid.uuid4()), db=db,
    )


async def test_a_nurse_reports_a_machine_down_with_a_reason_and_it_is_recorded(db):
    _facility, admin, nurse = await _setup(db)
    machine = await _register(db, admin, location="ICU", asset_tag="VENT-001")
    with pytest.raises(HTTPException) as refused:
        await _status(db, nurse, machine.id, "down")
    assert refused.value.detail["code"] == "reason_required"
    down = await _status(db, nurse, machine.id, "down", "Oxygen sensor fault")
    assert (down.status, down.status_reason) == ("down", "Oxygen sensor fault")
    back = await _status(db, nurse, machine.id, "working")
    assert back.status == "working"
    events = (await db.execute(select(EquipmentStatusEvent.to_status).where(
        EquipmentStatusEvent.equipment_id == machine.id).order_by(EquipmentStatusEvent.changed_at))).scalars().all()
    assert events == ["working", "down", "working"]


async def test_a_repeat_with_the_same_key_replays_instead_of_changing_twice(db):
    _facility, admin, nurse = await _setup(db)
    machine = await _register(db, admin)
    first = await _status(db, nurse, machine.id, "down", "No power", key="k-1")
    again = await _status(db, nurse, machine.id, "down", "No power", key="k-1")
    assert first == again


async def test_only_an_admin_retires_and_a_retired_machine_stays_retired(db):
    _facility, admin, nurse = await _setup(db)
    machine = await _register(db, admin)
    with pytest.raises(HTTPException) as refused:
        await _status(db, nurse, machine.id, "retired", "old")
    assert refused.value.status_code == 403
    await _status(db, admin, machine.id, "retired", "Condemned")
    with pytest.raises(HTTPException) as refused:
        await _status(db, admin, machine.id, "working")
    assert refused.value.detail["code"] == "equipment_retired"


async def test_an_asset_tag_is_unique_within_a_facility(db):
    _facility, admin, _nurse = await _setup(db)
    await _register(db, admin, asset_tag="XR-1")
    with pytest.raises(HTTPException) as refused:
        await _register(db, admin, asset_tag=" XR-1 ")
    assert refused.value.status_code == 409


async def test_another_facilitys_machine_is_not_found(db):
    _f, admin, _n = await _setup(db)
    _g, other_admin, _m = await _setup(db)
    machine = await _register(db, admin)
    with pytest.raises(HTTPException) as refused:
        await _status(db, other_admin, machine.id, "down", "x")
    assert refused.value.status_code == 404

"""A scan is booked on a machine from the equipment register (QA 12 Oct 2026).

Free text saved "xr-01" and "XR-01" as two machines.
"""
import uuid

import pytest
from fastapi import HTTPException

from app.equipment.models import Equipment
from app.radiology.router import _registered_machine
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def _facility(db):
    facility = Facility(id=uuid.uuid4(), name="Rad DH", code=f"R{uuid.uuid4().hex[:5].upper()}", state_code="DL")
    db.add(facility)
    user = User(id=uuid.uuid4(), facility_id=facility.id, keycloak_sub=f"s-{uuid.uuid4().hex[:8]}",
                username=f"r-{uuid.uuid4().hex[:8]}", full_name="Admin", is_active=True)
    db.add(user)
    await db.flush()
    facility.admin_id = user.id
    return facility


async def test_free_text_is_normalised_where_no_machine_is_registered(db):
    facility = await _facility(db)
    assert await _registered_machine(db, facility.id, " xr-01 ") == "XR-01"


async def test_a_registered_machine_is_matched_without_case_and_down_ones_refused(db):
    facility = await _facility(db)
    db.add_all([
        Equipment(id=uuid.uuid4(), facility_id=facility.id, name="X-ray Room 1", category="imaging",
                  asset_tag="XR-01", status="working", created_by=facility.admin_id),
        Equipment(id=uuid.uuid4(), facility_id=facility.id, name="CT Scanner", category="imaging",
                  asset_tag="CT-01", status="down", created_by=facility.admin_id),
    ])
    await db.flush()
    assert await _registered_machine(db, facility.id, "xr-01") == "X-ray Room 1"
    assert await _registered_machine(db, facility.id, "x-ray room 1") == "X-ray Room 1"
    with pytest.raises(HTTPException) as down:
        await _registered_machine(db, facility.id, "CT-01")
    assert down.value.detail["code"] == "machine_unavailable"
    with pytest.raises(HTTPException) as unknown:
        await _registered_machine(db, facility.id, "Room 9")
    assert unknown.value.detail["code"] == "machine_not_registered"

"""Beds can be added to a ward and taken out of service (QA 10 Oct 2026).

No API, screen or seed created beds, so a new facility's wards had none and
nobody could be admitted.
"""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.admissions.models import Ward
from app.users.models import Facility, User
from app.wards import router as wards

pytestmark = pytest.mark.asyncio


async def _ward(db):
    facility = Facility(id=uuid.uuid4(), name="Bed DH", code=f"B{uuid.uuid4().hex[:5].upper()}", state_code="DL")
    db.add(facility)
    await db.flush()
    admin = User(id=uuid.uuid4(), facility_id=facility.id, keycloak_sub=f"s-{uuid.uuid4().hex[:8]}",
                 username=f"a-{uuid.uuid4().hex[:8]}", full_name="Admin", is_active=True)
    db.add(admin)
    ward = Ward(id=uuid.uuid4(), name="General", facility_id=facility.id, is_active=True)
    db.add(ward)
    await db.flush()
    return ward, SimpleNamespace(id=admin.id, facility_id=facility.id)


async def test_an_admin_adds_a_bed_once(db):
    ward, admin = await _ward(db)
    first = await wards.add_bed(ward.id, wards.BedCreate(bed_number=" a-1 "), current_db_user=admin, db=db)
    again = await wards.add_bed(ward.id, wards.BedCreate(bed_number="A-1"), current_db_user=admin, db=db)
    assert (first.bed_number, first.status, again.id) == ("A-1", "vacant", first.id)


async def test_another_facilitys_ward_is_not_found(db):
    ward, _ = await _ward(db)
    _, other_admin = await _ward(db)
    with pytest.raises(HTTPException) as refused:
        await wards.add_bed(ward.id, wards.BedCreate(bed_number="1"), current_db_user=other_admin, db=db)
    assert refused.value.status_code == 404


async def test_a_bed_goes_out_of_service_and_back_with_a_reason(db):
    ward, admin = await _ward(db)
    bed = await wards.add_bed(ward.id, wards.BedCreate(bed_number="7"), current_db_user=admin, db=db)
    out = await wards.change_bed_status(
        bed.id, wards.BedStatusChange(status="maintenance", reason="Broken rail"), current_db_user=admin, db=db)
    assert out.status == "maintenance"
    back = await wards.change_bed_status(
        bed.id, wards.BedStatusChange(status="vacant", reason="Rail fixed"), current_db_user=admin, db=db)
    assert back.status == "vacant"

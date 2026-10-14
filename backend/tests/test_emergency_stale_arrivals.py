"""Old emergency visits are flagged, not mixed into 'awaiting care' (QA 10 Oct 2026).

Visits from 2 and 5 September were still listed as awaiting care on 10 October.
They are flagged stale after 24 hours for review; nothing closes them on a timer.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.emergency.service import get_emergency_worklist
from app.opd.models import Visit
from app.patients.models import Patient
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def test_an_arrival_older_than_a_day_is_flagged_stale(db):
    facility = Facility(id=uuid.uuid4(), name="ED DH", code=f"E{uuid.uuid4().hex[:5].upper()}", state_code="DL")
    db.add(facility)
    await db.flush()
    user = User(id=uuid.uuid4(), facility_id=facility.id, keycloak_sub=f"s-{uuid.uuid4().hex[:8]}",
                username=f"e-{uuid.uuid4().hex[:8]}", full_name="ED", is_active=True)
    db.add(user)
    patient = Patient(id=uuid.uuid4(), facility_id=facility.id, thid=f"TH-{uuid.uuid4().hex[:8]}",
                      full_name="Unknown", sex="other", age_years=30, status="active", identity_path="thid",
                      created_by=user.id)
    db.add(patient)
    await db.flush()
    now = datetime.now(UTC)
    for days, number in ((0, "NEW"), (35, "OLD")):
        db.add(Visit(id=uuid.uuid4(), visit_number=f"VST-{number}-{uuid.uuid4().hex[:4]}", patient_id=patient.id,
                     facility_id=facility.id, visit_type="emergency", status="registered",
                     visit_date=now - timedelta(days=days), created_at=now - timedelta(days=days),
                     created_by=user.id))
    await db.flush()
    rows = await get_emergency_worklist(db, facility.id)
    flags = {r["visit_number"].split("-")[1]: r["stale"] for r in rows}
    assert flags == {"NEW": False, "OLD": True}

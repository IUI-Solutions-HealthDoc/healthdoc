"""Reclassifying a visit — OPD escalated to IPD, IPD corrected to day care.

The rule worth testing is the refusal, not the happy path: a visit that
currently occupies a bed cannot be moved to a type that does not occupy one
while its admission is still open. Allowing it strands the bed — `admissions`
keeps pointing at it for a visit the ward census no longer counts, so the bed
reads occupied forever and only manual SQL clears it.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.common.enums import AdmissionStatus, VisitType
from app.opd import service

pytestmark = pytest.mark.asyncio


class _Visit:
    """Minimal stand-in — change_visit_type only touches these fields."""

    def __init__(self, visit_type: str):
        self.id = uuid.uuid4()
        self.visit_type = visit_type
        self.row_version = 1
        self.updated_by = None


@pytest.fixture
async def bedded(db, seed):
    """A facility with a patient, a ward and one bed.

    The shared `seed` fixture stops at department/room/doctor, so the two
    bed-strand tests below build the rest here rather than widening a fixture
    every other module depends on.
    """
    from app.patients.models import Patient
    from app.admissions.models import Bed, Ward

    dept, room, doctor = seed
    patient = Patient(
        id=uuid.uuid4(), facility_id=dept.facility_id, full_name="Bedded Patient",
        sex="female", age_years=44,  # dob-or-age is a CHECK, not optional
        uhid=f"UH{uuid.uuid4().hex[:8].upper()}",
        identity_path="demographics_only", identity_status="identity_unverified",
        created_by=doctor.id,
    )
    ward = Ward(id=uuid.uuid4(), facility_id=dept.facility_id,
                department_id=dept.id, name="Test Ward")
    db.add_all([patient, ward])
    await db.flush()
    bed = Bed(id=uuid.uuid4(), ward_id=ward.id, bed_number=f"B{uuid.uuid4().hex[:4]}")
    db.add(bed)
    await db.flush()
    return {"facility_id": dept.facility_id, "department_id": dept.id,
            "patient_id": patient.id, "user_id": doctor.id,
            "ward_id": ward.id, "bed_id": bed.id}


async def _change(db, visit, new_type):
    return await service.change_visit_type(
        db, visit=visit, new_type=new_type, reason="clinical decision", updated_by=uuid.uuid4()
    )


async def test_opd_can_be_escalated_to_ipd(db):
    visit = _Visit("opd")
    updated, previous = await _change(db, visit, "ipd")
    assert previous == "opd"
    assert updated.visit_type == "ipd"
    assert updated.row_version == 2


async def test_day_care_is_a_valid_target(db):
    """The type this whole change exists for."""
    visit = _Visit("opd")
    updated, _ = await _change(db, visit, "day_care")
    assert updated.visit_type == "day_care"


async def test_day_care_occupies_a_bed():
    """Not a behaviour of the endpoint — a fact the endpoint depends on.

    Ward occupancy and the strand guard both read this set. If day_care ever
    drops out of it, a day-care patient stops being counted in the bed census
    and the guard below silently stops protecting them.
    """
    assert VisitType.DAY_CARE.value in VisitType.bed_occupying()
    assert VisitType.IPD.value in VisitType.bed_occupying()
    assert VisitType.OPD.value not in VisitType.bed_occupying()


async def test_an_unknown_type_is_refused_by_name(db):
    visit = _Visit("opd")
    with pytest.raises(service.InvalidVisitTypeChange) as caught:
        await _change(db, visit, "inpatient")
    assert "not a visit type" in str(caught.value)


async def test_changing_to_the_same_type_is_refused(db):
    """Silently succeeding would write an audit row saying nothing changed."""
    visit = _Visit("opd")
    with pytest.raises(service.InvalidVisitTypeChange):
        await _change(db, visit, "opd")


@pytest.mark.parametrize(
    "occupying_status",
    [AdmissionStatus.ADMITTED.value, AdmissionStatus.TRANSFERRED.value],
)
async def test_a_visit_in_a_bed_cannot_be_moved_out_of_one(db, bedded, occupying_status):
    """The refusal that matters.

    TRANSFERRED is parametrised deliberately: a transferred patient moved to a
    different bed, they did not leave. Checking only ADMITTED would let them be
    reclassified out of IPD while still lying in one.
    """
    from app.admissions.models import Admission
    from app.opd.models import Visit

    visit = Visit(
        # Explicit id: under the SQLite fixture uuid_generate_v4() returns a
        # STRING, so a row inserted with the server default cannot be UPDATEd
        # afterwards — StaleDataError, 0 rows matched. See CLAUDE.md.
        id=uuid.uuid4(),
        patient_id=bedded["patient_id"], facility_id=bedded["facility_id"],
        department_id=bedded["department_id"], visit_type="ipd",
        visit_number=f"VST-T-{uuid.uuid4().hex[:6]}", status="registered",
        visit_date=datetime(2026, 9, 1, 9, tzinfo=UTC), created_by=bedded["user_id"],
    )
    db.add(visit)
    await db.flush()

    db.add(
        Admission(
            id=uuid.uuid4(), visit_id=visit.id, patient_id=bedded["patient_id"],
            ward_id=bedded["ward_id"], bed_id=bedded["bed_id"],
            admitted_at=datetime(2026, 9, 1, 9, tzinfo=UTC),
            status=occupying_status, created_by=bedded["user_id"],
        )
    )
    await db.flush()

    with pytest.raises(service.InvalidVisitTypeChange) as caught:
        await _change(db, visit, "opd")
    assert "still occupies a bed" in str(caught.value)


async def test_ipd_may_still_become_day_care_while_in_a_bed(db, bedded):
    """Both occupy a bed, so nothing is stranded — this must NOT be refused.

    A guard that blocked every change out of IPD would stop the correction
    people actually need: an overnight stay recorded as IPD that turns out to
    have been a day-care procedure.
    """
    from app.admissions.models import Admission
    from app.opd.models import Visit

    visit = Visit(
        # Explicit id: under the SQLite fixture uuid_generate_v4() returns a
        # STRING, so a row inserted with the server default cannot be UPDATEd
        # afterwards — StaleDataError, 0 rows matched. See CLAUDE.md.
        id=uuid.uuid4(),
        patient_id=bedded["patient_id"], facility_id=bedded["facility_id"],
        department_id=bedded["department_id"], visit_type="ipd",
        visit_number=f"VST-D-{uuid.uuid4().hex[:6]}", status="registered",
        visit_date=datetime(2026, 9, 1, 9, tzinfo=UTC), created_by=bedded["user_id"],
    )
    db.add(visit)
    await db.flush()
    db.add(
        Admission(
            id=uuid.uuid4(), visit_id=visit.id, patient_id=bedded["patient_id"],
            ward_id=bedded["ward_id"], bed_id=bedded["bed_id"],
            admitted_at=datetime(2026, 9, 1, 9, tzinfo=UTC),
            status="admitted", created_by=bedded["user_id"],
        )
    )
    await db.flush()

    updated, previous = await _change(db, visit, "day_care")
    assert previous == "ipd"
    assert updated.visit_type == "day_care"

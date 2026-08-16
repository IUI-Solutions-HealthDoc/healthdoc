"""
Integrity tests for migration 0034 (uq_admissions_active_bed,
ck_discharges_transfer_destination). Runs on the shared in-memory
SQLite fixture since both rules are plain SQL, not a Postgres-only
trigger.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.admissions.models import Admission, Discharge
from app.users.models import Facility
from tests.admissions.conftest import seed_bed, seed_patient, seed_visit

pytestmark = pytest.mark.asyncio


class TestActiveBedUniqueness:
    async def test_second_admission_to_occupied_bed_is_rejected(self, db, seed, ward, bed, admission):
        dept, _room, doctor = seed
        other_patient = await seed_patient(db, facility_id=dept.facility_id, created_by=doctor.id)
        other_visit = await seed_visit(db, facility_id=dept.facility_id, patient_id=other_patient.id, created_by=doctor.id)
        dupe = Admission(
            id=uuid.uuid4(), visit_id=other_visit.id, patient_id=other_patient.id,
            ward_id=ward.id, bed_id=bed.id, admitted_at=datetime.now(timezone.utc),
            status="admitted", created_by=doctor.id,
        )
        db.add(dupe)
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_second_admission_to_same_bed_ok_once_first_is_no_longer_admitted(self, db, seed, ward, bed, admission):
        dept, _room, doctor = seed
        admission.status = "discharged"
        await db.flush()
        other_patient = await seed_patient(db, facility_id=dept.facility_id, created_by=doctor.id)
        other_visit = await seed_visit(db, facility_id=dept.facility_id, patient_id=other_patient.id, created_by=doctor.id)
        new_admission = Admission(
            id=uuid.uuid4(), visit_id=other_visit.id, patient_id=other_patient.id,
            ward_id=ward.id, bed_id=bed.id, admitted_at=datetime.now(timezone.utc),
            status="admitted", created_by=doctor.id,
        )
        db.add(new_admission)
        await db.flush()

    async def test_admission_to_a_different_bed_is_unaffected(self, db, seed, ward, bed, admission):
        dept, _room, doctor = seed
        other_bed = await seed_bed(db, ward_id=ward.id, bed_number="2")
        other_patient = await seed_patient(db, facility_id=dept.facility_id, created_by=doctor.id)
        other_visit = await seed_visit(db, facility_id=dept.facility_id, patient_id=other_patient.id, created_by=doctor.id)
        second = Admission(
            id=uuid.uuid4(), visit_id=other_visit.id, patient_id=other_patient.id,
            ward_id=ward.id, bed_id=other_bed.id, admitted_at=datetime.now(timezone.utc),
            status="admitted", created_by=doctor.id,
        )
        db.add(second)
        await db.flush()


class TestTransferDestinationCheck:
    async def test_transferred_with_no_destination_is_rejected(self, db, seed, admission):
        _dept, _room, doctor = seed
        discharge = Discharge(
            id=uuid.uuid4(), admission_id=admission.id, discharged_at=datetime.now(timezone.utc),
            created_by=doctor.id, discharge_type="transferred",
        )
        db.add(discharge)
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_transferred_with_destination_facility_id_succeeds(self, db, seed, admission):
        _dept, _room, doctor = seed
        other_facility = Facility(id=uuid.uuid4(), code="DST01", name="Destination Facility", state_code="TS")
        db.add(other_facility)
        await db.flush()
        discharge = Discharge(
            id=uuid.uuid4(), admission_id=admission.id, discharged_at=datetime.now(timezone.utc),
            created_by=doctor.id, discharge_type="transferred", destination_facility_id=other_facility.id,
        )
        db.add(discharge)
        await db.flush()

    async def test_transferred_with_destination_facility_name_succeeds(self, db, seed, admission):
        _dept, _room, doctor = seed
        discharge = Discharge(
            id=uuid.uuid4(), admission_id=admission.id, discharged_at=datetime.now(timezone.utc),
            created_by=doctor.id, discharge_type="transferred",
            destination_facility_name="District Hospital, Sikar (external)",
        )
        db.add(discharge)
        await db.flush()

    async def test_non_transferred_discharge_needs_no_destination(self, db, seed, admission):
        _dept, _room, doctor = seed
        discharge = Discharge(
            id=uuid.uuid4(), admission_id=admission.id, discharged_at=datetime.now(timezone.utc),
            created_by=doctor.id, discharge_type="discharged",
        )
        db.add(discharge)
        await db.flush()

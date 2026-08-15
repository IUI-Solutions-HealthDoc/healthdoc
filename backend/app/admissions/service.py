"""backend/app/admissions/service.py -- #216 (B3-W5-01): IPD admission
and transfers. Discharge + FHIR stub land in a follow-up PR stacked on
this one (kept out here to stay under the team's PR-size guideline).

Audit: manual write_audit_log() calls, not the __audit_resource_type__
auto-audit path -- admissions/beds have no facility_id column of their
own (matches §3; adding one would be a migration this PR doesn't
need), so facility_id is resolved from the visit and passed explicitly,
same reason app/pathology and app/radiology do it manually.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import Admission, Bed, Discharge, DischargeNotification, PatientMovementLog
from app.audit.service import write_audit_log
# Reused from billing.service rather than duplicated -- pure auth/identity
# helper (keycloak_sub -> users.id), not billing-specific. Candidate for
# a shared module (app/common/ or app/auth/) in a future cleanup PR.
from app.billing.service import resolve_actor_user_id
from app.integrations.abdm.fhir import service as fhir_service
from app.opd.models import Visit


class VisitNotFound(Exception):
    def __init__(self, visit_id: UUID):
        self.visit_id = visit_id


class BedNotFound(Exception):
    def __init__(self, bed_id: UUID):
        self.bed_id = bed_id


class BedNotAvailable(Exception):
    def __init__(self, bed_id: UUID):
        self.bed_id = bed_id


class AdmissionNotFound(Exception):
    def __init__(self, admission_id: UUID):
        self.admission_id = admission_id


class AdmissionNotActive(Exception):
    """Raised on transfer of an admission whose status is already
    something other than 'admitted' -- discharged, transferred out,
    deceased, absconded. All terminal; none can be transferred again."""

    def __init__(self, admission_id: UUID, current_status: str):
        self.admission_id = admission_id
        self.current_status = current_status


class TransferDestinationRequired(Exception):
    """Mirrors ck_discharges_transfer_destination (0034): discharge_type
    'transferred' needs a destination_facility_id or _name. Checked here
    too so the API returns a clean 422/409 instead of surfacing a raw
    Postgres CHECK-constraint error."""


_DISCHARGE_NOTIFICATION_TARGETS = ("pharmacy", "billing", "nursing", "lab", "radiology", "patient")


async def _active_admission_on_bed(db: AsyncSession, bed_id: UUID) -> Admission | None:
    result = await db.execute(
        select(Admission).where(Admission.bed_id == bed_id, Admission.status == "admitted")
    )
    return result.scalar_one_or_none()


async def admit_patient(
    db: AsyncSession,
    visit_id: UUID,
    ward_id: UUID,
    bed_id: UUID,
    created_by: UUID,
    reason: str | None = None,
    admitted_at: datetime | None = None,
) -> Admission:
    visit = await db.get(Visit, visit_id)
    if visit is None:
        raise VisitNotFound(visit_id)

    bed = await db.get(Bed, bed_id)
    if bed is None:
        raise BedNotFound(bed_id)
    if await _active_admission_on_bed(db, bed_id) is not None:
        raise BedNotAvailable(bed_id)

    admission = Admission(
        id=uuid.uuid4(), visit_id=visit_id, patient_id=visit.patient_id, ward_id=ward_id, bed_id=bed_id,
        admitted_at=admitted_at or datetime.now(timezone.utc), reason=reason, status="admitted",
        created_by=created_by,
    )
    db.add(admission)
    bed.status = "occupied"
    await db.flush()

    await write_audit_log(
        db, facility_id=visit.facility_id, action="create", resource_type="admissions",
        resource_id=admission.id, user_id=created_by, patient_id=visit.patient_id, visit_id=visit_id,
        new_value={"ward_id": str(ward_id), "bed_id": str(bed_id), "status": "admitted"},
    )
    return admission


async def transfer_patient(
    db: AsyncSession,
    admission: Admission,
    to_ward_id: UUID,
    to_bed_id: UUID,
    moved_by: UUID,
    reason: str | None = None,
) -> Admission:
    if admission.status != "admitted":
        raise AdmissionNotActive(admission.id, admission.status)

    to_bed = await db.get(Bed, to_bed_id)
    if to_bed is None:
        raise BedNotFound(to_bed_id)
    existing = await _active_admission_on_bed(db, to_bed_id)
    if existing is not None and existing.id != admission.id:
        raise BedNotAvailable(to_bed_id)

    old_ward_id, old_bed_id = admission.ward_id, admission.bed_id
    old_bed = await db.get(Bed, old_bed_id)

    db.add(PatientMovementLog(
        id=uuid.uuid4(), admission_id=admission.id, from_ward_id=old_ward_id, from_bed_id=old_bed_id,
        to_ward_id=to_ward_id, to_bed_id=to_bed_id, moved_at=datetime.now(timezone.utc),
        reason=reason, moved_by=moved_by,
    ))

    if old_bed is not None:
        old_bed.status = "vacant"
    to_bed.status = "occupied"
    admission.ward_id = to_ward_id
    admission.bed_id = to_bed_id
    admission.updated_by = moved_by
    await db.flush()

    visit = await db.get(Visit, admission.visit_id)
    await write_audit_log(
        db, facility_id=visit.facility_id, action="transfer", resource_type="admissions",
        resource_id=admission.id, user_id=moved_by, patient_id=admission.patient_id, visit_id=admission.visit_id,
        old_value={"ward_id": str(old_ward_id), "bed_id": str(old_bed_id)},
        new_value={"ward_id": str(to_ward_id), "bed_id": str(to_bed_id)},
    )
    return admission


async def get_admission(db: AsyncSession, admission_id: UUID) -> Admission | None:
    return await db.get(Admission, admission_id)


async def discharge_patient(
    db: AsyncSession,
    admission: Admission,
    discharge_type: str,
    created_by: UUID,
    discharge_summary: str | None = None,
    follow_up_date=None,
    destination_facility_id: UUID | None = None,
    destination_facility_name: str | None = None,
    discharged_at: datetime | None = None,
) -> Discharge:
    if admission.status != "admitted":
        raise AdmissionNotActive(admission.id, admission.status)
    if discharge_type == "transferred" and not (destination_facility_id or destination_facility_name):
        raise TransferDestinationRequired()

    discharge = Discharge(
        id=uuid.uuid4(), admission_id=admission.id, discharged_at=discharged_at or datetime.now(timezone.utc),
        discharge_type=discharge_type, discharge_summary=discharge_summary, follow_up_date=follow_up_date,
        destination_facility_id=destination_facility_id, destination_facility_name=destination_facility_name,
        created_by=created_by,
    )
    db.add(discharge)

    admission.status = discharge_type
    admission.updated_by = created_by

    bed = await db.get(Bed, admission.bed_id)
    if bed is not None:
        bed.status = "vacant"

    for target in _DISCHARGE_NOTIFICATION_TARGETS:
        db.add(DischargeNotification(id=uuid.uuid4(), discharge_id=discharge.id, target_module=target))

    await db.flush()

    visit = await db.get(Visit, admission.visit_id)
    await fhir_service.record_discharge_bundle(db, discharge, admission, visit.facility_id)

    await write_audit_log(
        db, facility_id=visit.facility_id, action="discharge", resource_type="discharges",
        resource_id=discharge.id, user_id=created_by, patient_id=admission.patient_id, visit_id=admission.visit_id,
        new_value={"discharge_type": discharge_type},
    )
    return discharge


async def get_movements(db: AsyncSession, admission_id: UUID) -> list[PatientMovementLog]:
    result = await db.execute(
        select(PatientMovementLog)
        .where(PatientMovementLog.admission_id == admission_id)
        .order_by(PatientMovementLog.moved_at.asc())
    )
    return list(result.scalars().all())


async def get_discharge(db: AsyncSession, admission_id: UUID) -> Discharge | None:
    result = await db.execute(select(Discharge).where(Discharge.admission_id == admission_id))
    return result.scalar_one_or_none()

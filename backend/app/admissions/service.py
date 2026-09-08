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
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import (
    Admission,
    Bed,
    Discharge,
    DischargeNotification,
    PatientMovementLog,
    Ward,
)
from app.audit.service import write_audit_log

# Reused from billing.service rather than duplicated -- pure auth/identity
# helper (keycloak_sub -> users.id), not billing-specific. Candidate for
# a shared module (app/common/ or app/auth/) in a future cleanup PR.
from app.billing.service import resolve_actor_user_id as resolve_actor_user_id
from app.integrations.abdm.fhir import service as fhir_service
from app.opd.models import Visit
from app.patients.models import Patient


class VisitNotFound(Exception):
    def __init__(self, visit_id: UUID):
        self.visit_id = visit_id


class BedNotFound(Exception):
    def __init__(self, bed_id: UUID):
        self.bed_id = bed_id


class BedNotAvailable(Exception):
    def __init__(self, bed_id: UUID):
        self.bed_id = bed_id


class WardNotFound(Exception):
    def __init__(self, ward_id: UUID):
        self.ward_id = ward_id


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


async def admit_patient(
    db: AsyncSession,
    visit_id: UUID,
    ward_id: UUID,
    bed_id: UUID,
    created_by: UUID,
    reason: str | None = None,
    admitted_at: datetime | None = None,
    facility_id: UUID | None = None,
) -> Admission:
    visit = await db.get(Visit, visit_id)
    if visit is None or (facility_id is not None and visit.facility_id != facility_id):
        raise VisitNotFound(visit_id)

    ward = await db.get(Ward, ward_id)
    if ward is None or (facility_id is not None and ward.facility_id != facility_id):
        raise WardNotFound(ward_id)

    bed = await db.get(Bed, bed_id)
    if bed is None or bed.ward_id != ward_id:
        raise BedNotFound(bed_id)
    if bed.status not in ("vacant", "reserved"):
        raise BedNotAvailable(bed_id)

    admission = Admission(
        id=uuid.uuid4(), visit_id=visit_id, patient_id=visit.patient_id, ward_id=ward_id, bed_id=bed_id,
        admitted_at=admitted_at or datetime.now(UTC), reason=reason, status="admitted",
        created_by=created_by,
    )
    db.add(admission)
    bed.status = "occupied"

    try:
        await db.flush()
    except IntegrityError as e:
        if getattr(e.orig, "sqlstate", None) == "23505":
            raise BedNotAvailable(bed_id)
        raise

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
    facility_id: UUID | None = None,
) -> Admission:
    if admission.status != "admitted":
        raise AdmissionNotActive(admission.id, admission.status)

    to_ward = await db.get(Ward, to_ward_id)
    if to_ward is None or (facility_id is not None and to_ward.facility_id != facility_id):
        raise WardNotFound(to_ward_id)
    to_bed = await db.get(Bed, to_bed_id)
    if to_bed is None or to_bed.ward_id != to_ward_id:
        raise BedNotFound(to_bed_id)
    if to_bed.status not in ("vacant", "reserved"):
        raise BedNotAvailable(to_bed_id)

    old_ward_id, old_bed_id = admission.ward_id, admission.bed_id
    old_bed = await db.get(Bed, old_bed_id)

    db.add(PatientMovementLog(
        id=uuid.uuid4(), admission_id=admission.id, from_ward_id=old_ward_id, from_bed_id=old_bed_id,
        to_ward_id=to_ward_id, to_bed_id=to_bed_id, moved_at=datetime.now(UTC),
        reason=reason, moved_by=moved_by,
    ))

    if old_bed is not None:
        old_bed.status = "vacant"
    to_bed.status = "occupied"
    admission.ward_id = to_ward_id
    admission.bed_id = to_bed_id
    admission.updated_by = moved_by

    try:
        await db.flush()
    except IntegrityError as e:
        if getattr(e.orig, "sqlstate", None) == "23505":
            raise BedNotAvailable(to_bed_id)
        raise

    visit = await db.get(Visit, admission.visit_id)
    await write_audit_log(
        db, facility_id=visit.facility_id, action="transfer", resource_type="admissions",
        resource_id=admission.id, user_id=moved_by, patient_id=admission.patient_id, visit_id=admission.visit_id,
        old_value={"ward_id": str(old_ward_id), "bed_id": str(old_bed_id)},
        new_value={"ward_id": str(to_ward_id), "bed_id": str(to_bed_id)},
    )
    return admission


async def get_admission(
    db: AsyncSession,
    admission_id: UUID,
    facility_id: UUID | None = None,
) -> Admission | None:
    if facility_id is None:
        return await db.get(Admission, admission_id)
    result = await db.execute(
        select(Admission)
        .join(Ward, Ward.id == Admission.ward_id)
        .where(Admission.id == admission_id, Ward.facility_id == facility_id)
    )
    return result.scalar_one_or_none()


async def list_admissions(
    db: AsyncSession,
    *,
    facility_id: UUID,
    admission_status: str | None = None,
) -> list[Admission]:
    """Facility-scoped IPD list used by the live dashboard."""
    query = (
        select(Admission)
        .join(Ward, Ward.id == Admission.ward_id)
        .where(Ward.facility_id == facility_id)
        .order_by(Admission.admitted_at.desc())
    )
    if admission_status is not None:
        query = query.where(Admission.status == admission_status)
    rows = await db.execute(query)
    return list(rows.scalars().all())


async def list_discharges(
    db: AsyncSession, *, facility_id: UUID
) -> list[Discharge]:
    """Facility-scoped discharge list, newest first."""
    rows = await db.execute(
        select(Discharge)
        .join(Admission, Admission.id == Discharge.admission_id)
        .join(Ward, Ward.id == Admission.ward_id)
        .where(Ward.facility_id == facility_id)
        .order_by(Discharge.discharged_at.desc())
    )
    return list(rows.scalars().all())


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
        id=uuid.uuid4(), admission_id=admission.id, discharged_at=discharged_at or datetime.now(UTC),
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
    if discharge.discharge_summary:
        from app.integrations.abdm.hip.publisher import publish_document

        await publish_document(db, kind="discharge", source_id=discharge.id,
                               visit=visit, actor_id=created_by)
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


async def get_ward_bed_grid(db: AsyncSession, ward_id: UUID, caller_facility_id: UUID) -> list[dict]:
    """One row per bed, with the occupant's identity if occupied --
    authenticated clinical view, unlike the public queue display.
    Matches §20.1 (nurses manage patient list + bed status together)."""
    ward = await db.get(Ward, ward_id)
    if ward is None or ward.facility_id != caller_facility_id:
        raise WardNotFound(ward_id)

    # One query for the whole ward, not one per bed. The first version ran
    # a per-bed active-admission lookup and a Patient fetch in the loop, so a
    # 40-bed ward cost 81 round trips -- and this is the screen a nurse
    # refreshes constantly.
    #
    # The admitted-status filter belongs in the ON clause, not WHERE: in WHERE
    # it would turn the outer join inner and drop every vacant bed, leaving a
    # grid that shows only occupied beds. That is exactly the kind of bug that
    # looks right in a one-bed test fixture, which is why
    # test_ward_bed_grid_lists_every_bed_in_a_mixed_ward exists.
    #
    # Safe to join rather than aggregate because uq_admissions_active_bed
    # (0034) is a partial unique on bed_id WHERE status='admitted' -- at most
    # one active admission per bed, so no bed can fan out into two rows.
    rows = await db.execute(
        select(
            Bed.id, Bed.bed_number, Bed.status,
            Admission.id, Admission.patient_id, Admission.admitted_at,
            Patient.full_name, Patient.uhid,
        )
        .select_from(Bed)
        .outerjoin(
            Admission,
            and_(Admission.bed_id == Bed.id, Admission.status == "admitted"),
        )
        .outerjoin(Patient, Patient.id == Admission.patient_id)
        .where(Bed.ward_id == ward_id)
        .order_by(Bed.bed_number)
    )

    grid = []
    for (bed_id, bed_number, bed_status,
         admission_id, patient_id, admitted_at, full_name, uhid) in rows.all():
        occupant = None
        if admission_id is not None:
            occupant = {
                "admission_id": admission_id,
                "patient_id": patient_id,
                "patient_name": full_name,
                "uhid": uhid,
                "admitted_at": admitted_at,
            }
        grid.append({
            "bed_id": bed_id,
            "bed_number": bed_number,
            "status": bed_status,
            "occupant": occupant,
        })
    return grid


async def reconcile_bed_status(db: AsyncSession, facility_id: UUID | None = None) -> list[dict]:
    """admissions is authoritative; beds.status is a mirror, updated in
    the same transaction as the admission -- this never writes, only
    reports where the two disagree, so a human decides how to fix it.
    Two ways to disagree:
      - bed says occupied, but no active admission points to it
      - bed says vacant/reserved/maintenance, but an active admission does
    Optionally scoped to one facility via ward_id -> wards.facility_id;
    omit for a full sweep across every facility."""
    beds_query = select(Bed)
    if facility_id is not None:
        beds_query = beds_query.join(Ward, Ward.id == Bed.ward_id).where(Ward.facility_id == facility_id)
    beds = (await db.execute(beds_query)).scalars().all()
 
    admissions_result = await db.execute(select(Admission).where(Admission.status == "admitted"))
    active_admissions_by_bed = {a.bed_id: a for a in admissions_result.scalars().all()}
 
    mismatches = []
    for bed in beds:
        active_admission = active_admissions_by_bed.get(bed.id)
 
        if bed.status == "occupied" and active_admission is None:
            mismatches.append({
                "bed_id": bed.id,
                "ward_id": bed.ward_id,
                "bed_status": bed.status,
                "active_admission_id": None,
                "issue": "bed marked occupied but no active admission points to it",
            })
        elif bed.status != "occupied" and active_admission is not None:
            mismatches.append({
                "bed_id": bed.id,
                "ward_id": bed.ward_id,
                "bed_status": bed.status,
                "active_admission_id": active_admission.id,
                "issue": f"bed marked '{bed.status}' but admission {active_admission.id} is active on it",
            })

    return mismatches

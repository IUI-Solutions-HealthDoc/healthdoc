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

from sqlalchemy import and_, case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import (
    Admission,
    AdmissionChecklistTask,
    Bed,
    ClinicalDisposition,
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


class ClinicalDispositionNotFound(Exception):
    def __init__(self, disposition_id: UUID):
        self.disposition_id = disposition_id


class ChecklistTaskNotFound(Exception):
    def __init__(self, task_id: UUID):
        self.task_id = task_id


class ChecklistSkipReasonRequired(Exception):
    pass


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

    bed_res = await db.execute(
        select(Bed).where(Bed.id == bed_id).with_for_update()
    )
    bed = bed_res.scalar_one_or_none()
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

    # HD-13: Auto-update matching pending disposition to admitted
    disposition_res = await db.execute(
        select(ClinicalDisposition).where(
            ClinicalDisposition.visit_id == visit_id,
            ClinicalDisposition.disposition_type == "admit",
            ClinicalDisposition.status == "pending",
        )
    )
    for disp in disposition_res.scalars().all():
        disp.status = "admitted"
        disp.updated_by = created_by

    # HD-16: Auto-seed standard admission checklist tasks
    standard_tasks = [
        ("id_wristband", "Verify patient identity & apply ID wristband", "identification", True),
        ("baseline_vitals", "Record baseline vital signs", "clinical", True),
        ("allergy_diet", "Confirm allergies, adverse reactions & dietary restrictions", "safety", True),
        ("med_reconciliation", "Medication reconciliation with current prescriptions", "pharmacy", True),
        ("fall_safety_risk", "Assess fall risk (Morse) and pressure injury risk", "safety", True),
        ("ward_orientation", "Ward orientation, nurse call-bell instruction & visiting guidance", "orientation", False),
    ]
    for task_code, title, category, is_mandatory in standard_tasks:
        db.add(AdmissionChecklistTask(
            id=uuid.uuid4(),
            admission_id=admission.id,
            facility_id=visit.facility_id,
            task_code=task_code,
            title=title,
            category=category,
            is_mandatory=is_mandatory,
            status="pending",
        ))

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
    # Row-lock the admission
    adm_res = await db.execute(
        select(Admission).where(Admission.id == admission.id).with_for_update()
    )
    locked_adm = adm_res.scalar_one_or_none()
    if locked_adm is None:
        raise AdmissionNotFound(admission.id)
    if locked_adm.status != "admitted":
        raise AdmissionNotActive(locked_adm.id, locked_adm.status)

    to_ward = await db.get(Ward, to_ward_id)
    if to_ward is None or (facility_id is not None and to_ward.facility_id != facility_id):
        raise WardNotFound(to_ward_id)

    # Row-lock target bed
    to_bed_res = await db.execute(
        select(Bed).where(Bed.id == to_bed_id).with_for_update()
    )
    to_bed = to_bed_res.scalar_one_or_none()
    if to_bed is None or to_bed.ward_id != to_ward_id:
        raise BedNotFound(to_bed_id)
    if to_bed.status not in ("vacant", "reserved"):
        raise BedNotAvailable(to_bed_id)

    old_ward_id, old_bed_id = locked_adm.ward_id, locked_adm.bed_id
    # Row-lock old bed
    old_bed_res = await db.execute(
        select(Bed).where(Bed.id == old_bed_id).with_for_update()
    )
    old_bed = old_bed_res.scalar_one_or_none()

    db.add(PatientMovementLog(
        id=uuid.uuid4(), admission_id=locked_adm.id, from_ward_id=old_ward_id, from_bed_id=old_bed_id,
        to_ward_id=to_ward_id, to_bed_id=to_bed_id, moved_at=datetime.now(UTC),
        reason=reason, moved_by=moved_by,
    ))

    if old_bed is not None:
        old_bed.status = "vacant"
    to_bed.status = "occupied"
    locked_adm.ward_id = to_ward_id
    locked_adm.bed_id = to_bed_id
    locked_adm.updated_by = moved_by

    try:
        await db.flush()
    except IntegrityError as e:
        if getattr(e.orig, "sqlstate", None) == "23505":
            raise BedNotAvailable(to_bed_id)
        raise

    visit = await db.get(Visit, locked_adm.visit_id)
    await write_audit_log(
        db, facility_id=visit.facility_id, action="transfer", resource_type="admissions",
        resource_id=locked_adm.id, user_id=moved_by, patient_id=locked_adm.patient_id, visit_id=locked_adm.visit_id,
        old_value={"ward_id": str(old_ward_id), "bed_id": str(old_bed_id)},
        new_value={"ward_id": str(to_ward_id), "bed_id": str(to_bed_id)},
    )
    return locked_adm


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


# ---------------- HD-13: CLINICAL DISPOSITIONS ----------------

async def create_clinical_disposition(
    db: AsyncSession,
    *,
    facility_id: UUID,
    patient_id: UUID,
    visit_id: UUID,
    disposition_type: str,
    created_by: UUID,
    priority: str = "routine",
    encounter_id: UUID | None = None,
    recommended_ward_id: UUID | None = None,
    recommended_department_id: UUID | None = None,
    reason: str | None = None,
    notes: str | None = None,
) -> ClinicalDisposition:
    visit = await db.get(Visit, visit_id)
    if visit is None or visit.facility_id != facility_id:
        raise VisitNotFound(visit_id)

    disp = ClinicalDisposition(
        id=uuid.uuid4(),
        facility_id=facility_id,
        patient_id=patient_id,
        visit_id=visit_id,
        encounter_id=encounter_id,
        disposition_type=disposition_type,
        priority=priority,
        recommended_ward_id=recommended_ward_id,
        recommended_department_id=recommended_department_id,
        reason=reason,
        status="pending",
        notes=notes,
        created_by=created_by,
    )
    db.add(disp)
    await db.flush()

    await write_audit_log(
        db,
        facility_id=facility_id,
        action="create",
        resource_type="clinical_dispositions",
        resource_id=disp.id,
        user_id=created_by,
        patient_id=patient_id,
        visit_id=visit_id,
        new_value={"disposition_type": disposition_type, "priority": priority, "status": "pending"},
    )
    return disp


async def list_pending_admissions(
    db: AsyncSession, *, facility_id: UUID
) -> list[dict]:
    from app.departments.models import Department
    from app.users.models import User

    query = (
        select(
            ClinicalDisposition.id.label("disposition_id"),
            Patient.id.label("patient_id"),
            Patient.full_name.label("patient_name"),
            Patient.uhid.label("patient_uhid"),
            Patient.sex.label("patient_sex"),
            Patient.dob.label("patient_dob"),
            Patient.age_years.label("patient_age_years"),
            Visit.id.label("visit_id"),
            Visit.visit_number.label("visit_number"),
            ClinicalDisposition.encounter_id,
            ClinicalDisposition.priority,
            ClinicalDisposition.recommended_ward_id,
            Ward.name.label("recommended_ward_name"),
            Ward.name_hi.label("recommended_ward_name_hi"),
            ClinicalDisposition.recommended_department_id,
            Department.name.label("recommended_department_name"),
            Department.name_hi.label("recommended_department_name_hi"),
            ClinicalDisposition.reason,
            ClinicalDisposition.created_by.label("doctor_id"),
            User.full_name.label("doctor_name"),
            ClinicalDisposition.created_at,
        )
        .join(Patient, Patient.id == ClinicalDisposition.patient_id)
        .join(Visit, Visit.id == ClinicalDisposition.visit_id)
        .outerjoin(Ward, Ward.id == ClinicalDisposition.recommended_ward_id)
        .outerjoin(Department, Department.id == ClinicalDisposition.recommended_department_id)
        .outerjoin(User, User.id == ClinicalDisposition.created_by)
        .where(
            ClinicalDisposition.facility_id == facility_id,
            ClinicalDisposition.disposition_type == "admit",
            ClinicalDisposition.status == "pending",
        )
        .order_by(
            case(
                (ClinicalDisposition.priority == "emergency", 1),
                (ClinicalDisposition.priority == "urgent", 2),
                else_=3,
            ),
            ClinicalDisposition.created_at.asc(),
        )
    )
    rows = await db.execute(query)
    results = []
    for r in rows.mappings():
        item = dict(r)
        age = item.get("patient_age_years")
        if age is None and item.get("patient_dob"):
            today = datetime.now(UTC).date()
            dob = item["patient_dob"]
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        item["patient_age"] = age
        item.pop("patient_dob", None)
        item.pop("patient_age_years", None)
        if not item.get("patient_uhid"):
            item["patient_uhid"] = "Pending UHID"
        results.append(item)
    return results


async def list_pending_discharges(
    db: AsyncSession, *, facility_id: UUID
) -> list[dict]:
    from app.users.models import User

    query = (
        select(
            Admission.id.label("admission_id"),
            Patient.id.label("patient_id"),
            Patient.full_name.label("patient_name"),
            Patient.uhid.label("patient_uhid"),
            Ward.id.label("ward_id"),
            Ward.name.label("ward_name"),
            Ward.name_hi.label("ward_name_hi"),
            Bed.id.label("bed_id"),
            Bed.bed_number.label("bed_number"),
            Admission.admitted_at,
            ClinicalDisposition.created_by.label("recommended_by_id"),
            User.full_name.label("recommended_by_name"),
            ClinicalDisposition.reason,
            ClinicalDisposition.created_at,
        )
        .join(Admission, Admission.patient_id == ClinicalDisposition.patient_id)
        .join(Patient, Patient.id == Admission.patient_id)
        .join(Ward, Ward.id == Admission.ward_id)
        .join(Bed, Bed.id == Admission.bed_id)
        .outerjoin(User, User.id == ClinicalDisposition.created_by)
        .where(
            ClinicalDisposition.facility_id == facility_id,
            ClinicalDisposition.disposition_type == "discharge",
            ClinicalDisposition.status == "pending",
            Admission.status == "admitted",
        )
        .order_by(ClinicalDisposition.created_at.asc())
    )
    rows = await db.execute(query)
    results = []
    for r in rows.mappings():
        item = dict(r)
        if not item.get("patient_uhid"):
            item["patient_uhid"] = "Pending UHID"
        results.append(item)
    return results


async def update_clinical_disposition(
    db: AsyncSession,
    disposition_id: UUID,
    *,
    status: str | None = None,
    notes: str | None = None,
    updated_by: UUID,
    facility_id: UUID,
) -> ClinicalDisposition:
    disp = await db.get(ClinicalDisposition, disposition_id)
    if disp is None or disp.facility_id != facility_id:
        raise ClinicalDispositionNotFound(disposition_id)
    if status is not None:
        disp.status = status
    if notes is not None:
        disp.notes = notes
    disp.updated_by = updated_by
    await db.flush()
    await db.refresh(disp)
    return disp


# ---------------- HD-16: ADMISSION CHECKLIST ----------------

async def get_admission_checklist(
    db: AsyncSession, admission_id: UUID, facility_id: UUID
) -> list[dict]:
    from app.users.models import User

    admission = await get_admission(db, admission_id, facility_id)
    if admission is None:
        raise AdmissionNotFound(admission_id)

    query = (
        select(
            AdmissionChecklistTask,
            User.full_name.label("completed_by_name"),
        )
        .outerjoin(User, User.id == AdmissionChecklistTask.completed_by)
        .where(
            AdmissionChecklistTask.admission_id == admission_id,
            AdmissionChecklistTask.facility_id == facility_id,
        )
        .order_by(AdmissionChecklistTask.created_at.asc())
    )
    rows = await db.execute(query)
    items = []
    for task, completed_by_name in rows.all():
        data = {
            "id": task.id,
            "admission_id": task.admission_id,
            "task_code": task.task_code,
            "title": task.title,
            "category": task.category,
            "is_mandatory": task.is_mandatory,
            "status": task.status,
            "completed_at": task.completed_at,
            "completed_by": task.completed_by,
            "completed_by_name": completed_by_name,
            "skipped_reason": task.skipped_reason,
            "notes": task.notes,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }
        items.append(data)
    return items


async def update_checklist_task(
    db: AsyncSession,
    *,
    admission_id: UUID,
    task_id: UUID,
    status: str,
    skipped_reason: str | None = None,
    notes: str | None = None,
    updated_by: UUID,
    facility_id: UUID,
) -> dict:
    from app.users.models import User

    task = await db.get(AdmissionChecklistTask, task_id)
    if task is None or task.admission_id != admission_id or task.facility_id != facility_id:
        raise ChecklistTaskNotFound(task_id)

    if status == "skipped" and (not skipped_reason or not skipped_reason.strip()):
        raise ChecklistSkipReasonRequired("Mandatory skipped_reason is required when skipping a checklist task")

    task.status = status
    if status in ("completed", "skipped"):
        task.completed_at = datetime.now(UTC)
        task.completed_by = updated_by
    else:
        task.completed_at = None
        task.completed_by = None

    task.skipped_reason = skipped_reason.strip() if skipped_reason else None
    if notes is not None:
        task.notes = notes

    await db.flush()
    await db.refresh(task)

    user_name = None
    if task.completed_by:
        u = await db.get(User, task.completed_by)
        if u:
            user_name = u.full_name

    return {
        "id": task.id,
        "admission_id": task.admission_id,
        "task_code": task.task_code,
        "title": task.title,
        "category": task.category,
        "is_mandatory": task.is_mandatory,
        "status": task.status,
        "completed_at": task.completed_at,
        "completed_by": task.completed_by,
        "completed_by_name": user_name,
        "skipped_reason": task.skipped_reason,
        "notes": task.notes,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


# ---------------- HD-15: ADMISSION CHART ----------------

async def get_admission_chart(
    db: AsyncSession, admission_id: UUID, facility_id: UUID
) -> dict:
    admission = await get_admission(db, admission_id, facility_id)
    if admission is None:
        raise AdmissionNotFound(admission_id)

    patient = await db.get(Patient, admission.patient_id)
    ward = await db.get(Ward, admission.ward_id)
    bed = await db.get(Bed, admission.bed_id)

    # Patient info
    patient_info = {
        "id": str(patient.id) if patient else "",
        "full_name": patient.full_name if patient else "",
        "uhid": patient.uhid or "Pending UHID" if patient else "",
        "sex": getattr(patient, "sex", None),
        "dob": str(patient.dob) if patient and getattr(patient, "dob", None) else None,
        "age_years": getattr(patient, "age_years", None),
        "mobile": getattr(patient, "mobile", None),
    }

    # Admission info
    admission_info = {
        "id": str(admission.id),
        "admitted_at": admission.admitted_at.isoformat() if admission.admitted_at else None,
        "status": admission.status,
        "ward_id": str(admission.ward_id),
        "ward_name": ward.name if ward else "",
        "ward_name_hi": getattr(ward, "name_hi", None) if ward else None,
        "bed_id": str(admission.bed_id),
        "bed_number": bed.bed_number if bed else "",
        "reason": admission.reason,
    }

    # Vitals (filtered by admission_id or patient_id)
    from app.nursing.models import Vitals
    vitals_res = await db.execute(
        select(Vitals)
        .where(
            (Vitals.admission_id == admission_id) |
            ((Vitals.patient_id == admission.patient_id) & (Vitals.measured_at >= admission.admitted_at))
        )
        .order_by(Vitals.measured_at.desc())
        .limit(20)
    )
    vitals_list = []
    for v in vitals_res.scalars().all():
        vitals_list.append({
            "id": str(v.id),
            "measured_at": v.measured_at.isoformat() if v.measured_at else None,
            "temp_c": float(v.temp_c) if v.temp_c is not None else None,
            "pulse_bpm": v.pulse_bpm,
            "resp_rate": v.resp_rate,
            "bp_systolic": v.bp_systolic,
            "bp_diastolic": v.bp_diastolic,
            "spo2_pct": v.spo2_pct,
            "pain_score": v.pain_score,
        })

    # Allergies
    from app.allergies.models import Allergy
    allergies_res = await db.execute(
        select(Allergy)
        .where(Allergy.patient_id == admission.patient_id, Allergy.status == "active")
        .order_by(Allergy.created_at.desc())
    )
    allergies_list = []
    for a in allergies_res.scalars().all():
        allergies_list.append({
            "id": str(a.id),
            "allergen_type": a.allergen_type,
            "substance_text": a.substance_text,
            "severity": a.severity,
            "reaction": a.reaction,
            "is_blocking": a.is_blocking,
        })

    # Diagnoses
    from app.opd.models import Diagnosis, Encounter
    diagnoses_res = await db.execute(
        select(Diagnosis)
        .join(Encounter, Encounter.id == Diagnosis.encounter_id)
        .where(Encounter.visit_id == admission.visit_id)
        .order_by(Diagnosis.is_primary.desc(), Diagnosis.created_at.desc())
    )
    diagnoses_list = []
    for d in diagnoses_res.scalars().all():
        diagnoses_list.append({
            "id": str(d.id),
            "icd_code": d.icd_code,
            "icd_version": d.icd_version,
            "diagnosis_text": d.diagnosis_text,
            "diagnosis_type": d.diagnosis_type,
            "is_primary": d.is_primary,
        })

    # Orders (Labs, Radiology, Procedures)
    from app.orders.models import Order
    orders_res = await db.execute(
        select(Order)
        .where(Order.patient_id == admission.patient_id)
        .order_by(Order.ordered_at.desc())
        .limit(20)
    )
    orders_list = []
    for o in orders_res.scalars().all():
        orders_list.append({
            "id": str(o.id),
            "order_number": o.order_number,
            "order_type": o.order_type,
            "priority": o.priority,
            "status": o.status,
            "ordered_at": o.ordered_at.isoformat() if o.ordered_at else None,
        })

    # Medications (Prescriptions)
    from app.orders.models import Prescription, PrescriptionItem
    presc_res = await db.execute(
        select(PrescriptionItem)
        .join(Prescription, Prescription.id == PrescriptionItem.prescription_id)
        .where(Prescription.patient_id == admission.patient_id)
        .order_by(PrescriptionItem.created_at.desc())
        .limit(20)
    )
    medications_list = []
    for pi in presc_res.scalars().all():
        medications_list.append({
            "id": str(pi.id),
            "medicine_name": pi.medicine_name,
            "dosage": pi.dosage,
            "frequency": pi.frequency,
            "duration_days": pi.duration_days,
            "route": pi.route,
            "status": pi.status,
            "instructions": pi.instructions,
        })

    # Checklist summary
    tasks_res = await db.execute(
        select(AdmissionChecklistTask).where(AdmissionChecklistTask.admission_id == admission.id)
    )
    all_tasks = tasks_res.scalars().all()
    completed_count = sum(1 for t in all_tasks if t.status == "completed")
    skipped_count = sum(1 for t in all_tasks if t.status == "skipped")
    pending_count = sum(1 for t in all_tasks if t.status == "pending")
    total_count = len(all_tasks)

    checklist_summary = {
        "total": total_count,
        "completed": completed_count,
        "skipped": skipped_count,
        "pending": pending_count,
        "percent_complete": round((completed_count + skipped_count) / total_count * 100) if total_count > 0 else 0,
    }

    return {
        "admission_id": admission.id,
        "patient": patient_info,
        "admission": admission_info,
        "vitals": vitals_list,
        "allergies": allergies_list,
        "diagnoses": diagnoses_list,
        "orders": orders_list,
        "medications": medications_list,
        "checklist_summary": checklist_summary,
    }

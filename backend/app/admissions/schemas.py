"""backend/app/admissions/schemas.py -- request/response models for #216
(B3-W5-01): IPD admission and transfers. Discharge schemas land in the
follow-up PR that adds discharge_patient()."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, field_validator

#: A clinical time may run slightly ahead of the server clock (a ward PC's
#: clock drift); beyond this it is a typo or a time-zone slip, not care given.
_FUTURE_TOLERANCE = timedelta(minutes=5)


def _not_in_future(value: datetime | None) -> datetime | None:
    if value is not None and value > datetime.now(UTC) + _FUTURE_TOLERANCE:
        raise ValueError("cannot be in the future")
    return value


class AdmissionCreate(BaseModel):
    visit_id: UUID
    ward_id: UUID
    bed_id: UUID
    reason: str | None = None
    #: Must carry its UTC offset. A bare "2026-10-09T14:33" was read as UTC,
    #: so an admission entered at 14:33 IST was stored 5½ hours in the future
    #: (live, 9 Oct 2026). Refusing it is safer than guessing the zone.
    admitted_at: AwareDatetime | None = None

    _admitted_not_future = field_validator("admitted_at")(_not_in_future)


class AdmissionOut(BaseModel):
    id: UUID
    visit_id: UUID
    patient_id: UUID
    ward_id: UUID
    bed_id: UUID
    admitted_at: datetime
    reason: str | None
    status: str
    model_config = {"from_attributes": True}


class TransferRequest(BaseModel):
    to_ward_id: UUID
    to_bed_id: UUID
    reason: str | None = None


class DischargeRequest(BaseModel):
    discharge_type: str = Field(..., description="discharged | dama | deceased | absconded | transferred")
    discharge_summary: str | None = None
    follow_up_date: date | None = None
    destination_facility_id: UUID | None = None
    destination_facility_name: str | None = None
    #: Must carry its UTC offset, as admitted_at does.
    discharged_at: AwareDatetime | None = None

    _discharged_not_future = field_validator("discharged_at")(_not_in_future)


class DischargeOut(BaseModel):
    id: UUID
    admission_id: UUID
    discharged_at: datetime
    discharge_type: str
    discharge_summary: str | None
    follow_up_date: date | None
    destination_facility_id: UUID | None
    destination_facility_name: str | None
    model_config = {"from_attributes": True}


class MovementOut(BaseModel):
    id: UUID
    admission_id: UUID
    from_ward_id: UUID | None
    from_bed_id: UUID | None
    to_ward_id: UUID
    to_bed_id: UUID
    moved_at: datetime
    reason: str | None
    model_config = {"from_attributes": True}


class DischargeSummaryOut(BaseModel):
    admission: AdmissionOut
    discharge: DischargeOut | None
    movements: list[MovementOut]


# ---------------- HD-13: CLINICAL DISPOSITIONS ----------------
class ClinicalDispositionCreate(BaseModel):
    patient_id: UUID
    visit_id: UUID
    encounter_id: UUID | None = None
    disposition_type: str = Field(..., description="admit | discharge | transfer | follow_up")
    priority: str = Field(default="routine", description="routine | urgent | emergency")
    recommended_ward_id: UUID | None = None
    recommended_department_id: UUID | None = None
    reason: str | None = None
    notes: str | None = None


class ClinicalDispositionUpdate(BaseModel):
    status: str | None = Field(default=None, description="pending | admitted | discharged | transferred | cancelled")
    notes: str | None = None


class ClinicalDispositionOut(BaseModel):
    id: UUID
    facility_id: UUID
    patient_id: UUID
    visit_id: UUID
    encounter_id: UUID | None
    disposition_type: str
    priority: str
    recommended_ward_id: UUID | None
    recommended_department_id: UUID | None
    reason: str | None
    status: str
    notes: str | None
    created_by: UUID | None
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class PendingAdmissionItemOut(BaseModel):
    disposition_id: UUID
    patient_id: UUID
    patient_name: str
    patient_uhid: str
    patient_sex: str | None = None
    patient_age: int | None = None
    visit_id: UUID
    visit_number: str
    encounter_id: UUID | None = None
    priority: str
    recommended_ward_id: UUID | None = None
    recommended_ward_name: str | None = None
    recommended_ward_name_hi: str | None = None
    recommended_department_id: UUID | None = None
    recommended_department_name: str | None = None
    recommended_department_name_hi: str | None = None
    reason: str | None = None
    doctor_id: UUID | None = None
    doctor_name: str | None = None
    created_at: datetime


class PendingDischargeItemOut(BaseModel):
    admission_id: UUID
    patient_id: UUID
    patient_name: str
    patient_uhid: str
    ward_id: UUID
    ward_name: str
    ward_name_hi: str | None = None
    bed_id: UUID
    bed_number: str
    admitted_at: datetime
    recommended_by_id: UUID | None = None
    recommended_by_name: str | None = None
    reason: str | None = None
    created_at: datetime


# ---------------- HD-16: ADMISSION CHECKLIST ----------------
class AdmissionChecklistTaskUpdate(BaseModel):
    status: str = Field(..., description="pending | completed | skipped")
    skipped_reason: str | None = None
    notes: str | None = None


class AdmissionChecklistTaskOut(BaseModel):
    id: UUID
    admission_id: UUID
    task_code: str
    title: str
    category: str
    is_mandatory: bool
    status: str
    completed_at: datetime | None = None
    completed_by: UUID | None = None
    completed_by_name: str | None = None
    skipped_reason: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ---------------- HD-15: ADMISSION CHART ----------------
class AdmissionChartOut(BaseModel):
    admission_id: UUID
    patient: dict
    admission: dict
    vitals: list[dict]
    allergies: list[dict]
    diagnoses: list[dict]
    orders: list[dict]
    medications: list[dict]
    checklist_summary: dict


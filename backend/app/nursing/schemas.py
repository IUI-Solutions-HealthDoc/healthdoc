"""backend/app/nursing/schemas.py -- /nursing request/response models (#390).

created_by comes from current_db_user, never the request body (same rule as
encounters/router.py and allergies/router.py).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.common.enums import (
    ClinicalIncidentSeverity, ClinicalIncidentStatus, ClinicalIncidentType,
    IntakeOutputType, MedicationAdministrationStatus, NursingShift,
)


def _one_of(enum_cls: type) -> str:
    return " | ".join(sorted(enum_cls.values()))


class VitalsCreate(BaseModel):
    patient_id: UUID
    encounter_id: UUID | None = Field(
        default=None, description="OPD path. Exactly one of encounter_id/admission_id.")
    admission_id: UUID | None = Field(
        default=None, description="IPD path. Exactly one of encounter_id/admission_id.")
    measured_at: datetime | None = Field(
        default=None,
        description="Clinical time of measurement. Defaults to now. May be backdated "
                    "when a paper observation is transcribed.",
    )

    height_cm: Decimal | None = Field(default=None, ge=0, le=300)
    weight_kg: Decimal | None = Field(default=None, ge=0, le=700)
    waist_cm: Decimal | None = Field(default=None, ge=0, le=300)
    hip_cm: Decimal | None = Field(default=None, ge=0, le=300)

    temp_c: Decimal | None = Field(default=None, ge=20, le=45)
    pulse_bpm: int | None = Field(default=None, ge=0, le=350)
    resp_rate: int | None = Field(default=None, ge=0, le=120)
    bp_systolic: int | None = Field(default=None, ge=0, le=350)
    bp_diastolic: int | None = Field(default=None, ge=0, le=250)
    spo2_pct: int | None = Field(default=None, ge=0, le=100)
    pain_score: int | None = Field(default=None, ge=0, le=10)

    @model_validator(mode="after")
    def _exactly_one_context(self) -> "VitalsCreate":
        # Mirrors ck_vitals_encounter_or_admission. Checked here too so the
        # caller gets a 422 naming the problem rather than a 500 from the DB.
        if (self.encounter_id is None) == (self.admission_id is None):
            raise ValueError(
                "exactly one of encounter_id or admission_id must be set — vitals "
                "belong to an OPD encounter or an IPD admission, never both")
        return self

    @model_validator(mode="after")
    def _bp_pair(self) -> "VitalsCreate":
        if self.bp_systolic is not None and self.bp_diastolic is not None:
            if self.bp_diastolic >= self.bp_systolic:
                raise ValueError("bp_diastolic must be lower than bp_systolic")
        return self


class VitalsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    encounter_id: UUID | None
    admission_id: UUID | None
    measured_at: datetime

    height_cm: Decimal | None
    weight_kg: Decimal | None
    #: Derived server-side from height and weight; never accepted from the client.
    bmi: Decimal | None
    waist_cm: Decimal | None
    hip_cm: Decimal | None
    whr: Decimal | None

    temp_c: Decimal | None
    pulse_bpm: int | None
    resp_rate: int | None
    bp_systolic: int | None
    bp_diastolic: int | None
    spo2_pct: int | None
    pain_score: int | None

    created_by: UUID
    created_at: datetime


class MedicationAdministrationCreate(BaseModel):
    prescription_item_id: UUID
    admission_id: UUID
    patient_id: UUID
    status: str = Field(..., description=_one_of(MedicationAdministrationStatus))
    scheduled_at: datetime | None = None
    administered_at: datetime | None = Field(
        default=None, description="Defaults to now.")
    dose_given: str | None = None
    reason: str | None = Field(
        default=None,
        description="Required for held and refused. An unexplained missed dose "
                    "cannot be reconstructed in an adverse-event review.",
    )
    notes: str | None = None

    @model_validator(mode="after")
    def _valid_status_and_reason(self) -> "MedicationAdministrationCreate":
        if self.status not in MedicationAdministrationStatus.values():
            raise ValueError(f"status must be one of: {_one_of(MedicationAdministrationStatus)}")
        if self.status != MedicationAdministrationStatus.GIVEN.value:
            if self.reason is None or not self.reason.strip():
                raise ValueError(f"reason is required when status is '{self.status}'")
        return self


class MedicationAdministrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prescription_item_id: UUID
    admission_id: UUID
    patient_id: UUID
    scheduled_at: datetime | None
    administered_at: datetime
    status: str
    dose_given: str | None
    reason: str | None
    notes: str | None
    created_by: UUID
    created_at: datetime

    #: Denormalised from prescription_items so an eMAR row can name its drug.
    #: Nullable because the join is a LEFT join — a dose that was given stays
    #: on the record even if its prescription item is gone.
    medicine_name: str | None = None
    #: What was PRESCRIBED. `dose_given` above is what the nurse recorded.
    dosage: str | None = None
    route: str | None = None


class IntakeOutputCreate(BaseModel):
    admission_id: UUID
    entry_type: str = Field(..., description=_one_of(IntakeOutputType))
    volume_ml: int = Field(..., gt=0, description="Always positive; direction comes from entry_type.")
    recorded_at: datetime | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _valid_type(self) -> "IntakeOutputCreate":
        if self.entry_type not in IntakeOutputType.values():
            raise ValueError(f"entry_type must be one of: {_one_of(IntakeOutputType)}")
        return self


class IntakeOutputOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    admission_id: UUID
    recorded_at: datetime
    entry_type: str
    volume_ml: int
    notes: str | None
    created_by: UUID
    created_at: datetime


class FluidBalanceOut(BaseModel):
    """Running totals for one admission. Direction is decided by entry_type,
    which is why volume_ml is stored unsigned."""

    admission_id: UUID
    total_intake_ml: int
    total_output_ml: int
    net_ml: int


# ============================================================ order check-off (#210)

class OrderTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    encounter_id: UUID | None = None
    order_type: str
    priority: str
    status: str
    ordered_at: datetime
    accepted_at: datetime | None
    accepted_by: UUID | None
    completed_at: datetime | None
    completed_by: UUID | None
    completion_note: str | None


class OrderCompleteRequest(BaseModel):
    note: str | None = Field(
        default=None,
        description="Optional. What is worth saying about how it went — "
                    "an unremarkable completion needs no comment.",
    )


# ============================================================ incidents (#236)

class IncidentReport(BaseModel):
    incident_type: str = Field(..., description=_one_of(ClinicalIncidentType))
    severity: str = Field(
        ..., description=_one_of(ClinicalIncidentSeverity)
        + " — harm that REACHED the patient, not harm risked. An event that "
          "never reached them is incident_type='near_miss'.")
    occurred_at: datetime
    description: str = Field(..., min_length=1)
    immediate_action: str = Field(
        ..., min_length=1,
        description="What was done for the patient straight away. Required — "
                    "an incident with no recorded response is the one a review "
                    "cannot defend.")

    patient_id: UUID | None = Field(
        default=None,
        description="Optional. A sharps injury to staff, or equipment found "
                    "faulty before use, has no patient.")
    admission_id: UUID | None = None
    department_id: UUID | None = None
    ward_id: UUID | None = None
    reported_at: datetime | None = Field(
        default=None, description="Defaults to now. Must not precede occurred_at.")

    @model_validator(mode="after")
    def _valid_enums_and_times(self) -> "IncidentReport":
        if self.incident_type not in ClinicalIncidentType.values():
            raise ValueError(f"incident_type must be one of: {_one_of(ClinicalIncidentType)}")
        if self.severity not in ClinicalIncidentSeverity.values():
            raise ValueError(f"severity must be one of: {_one_of(ClinicalIncidentSeverity)}")
        if self.reported_at is not None and self.reported_at < self.occurred_at:
            raise ValueError("reported_at cannot precede occurred_at")
        return self


class IncidentReviewRequest(BaseModel):
    status: str = Field(..., description=_one_of(ClinicalIncidentStatus))
    root_cause: str | None = None
    corrective_action: str | None = Field(
        default=None,
        description="Both this and root_cause are required to close. A register "
                    "of closed incidents with no findings teaches nobody anything.")

    @model_validator(mode="after")
    def _valid_status(self) -> "IncidentReviewRequest":
        if self.status not in ClinicalIncidentStatus.values():
            raise ValueError(f"status must be one of: {_one_of(ClinicalIncidentStatus)}")
        return self


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    facility_id: UUID
    department_id: UUID | None
    ward_id: UUID | None
    patient_id: UUID | None
    admission_id: UUID | None
    incident_type: str
    severity: str
    status: str
    occurred_at: datetime
    reported_at: datetime
    description: str
    immediate_action: str
    reported_by: UUID
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    root_cause: str | None
    corrective_action: str | None


class HandoverNoteCreate(BaseModel):
    """One SBAR shift handover.

    All four SBAR fields are required here even though the columns are
    nullable. The columns predate any writer; the structure is the safety
    mechanism, and a handover with the assessment left blank is the one nobody
    can act on. Loosen this only with a clinical reason, not to make a form
    easier to submit.
    """

    admission_id: UUID
    shift: NursingShift
    situation: str = Field(min_length=5, max_length=4000)
    background: str = Field(min_length=5, max_length=4000)
    assessment: str = Field(min_length=5, max_length=4000)
    recommendation: str = Field(min_length=5, max_length=4000)
    handed_over_to: UUID = Field(
        description="The receiving nurse. A handover to nobody is a note, not a handover.",
    )


class HandoverNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    admission_id: UUID
    shift: str
    situation: str | None
    background: str | None
    assessment: str | None
    recommendation: str | None
    handed_over_to: UUID
    #: Who handed over. Resolved for display so the ward board does not have to
    #: fetch a user per row.
    handed_over_to_name: str | None = None
    created_by: UUID
    created_by_name: str | None = None
    created_at: datetime


class HandoverNoteListOut(BaseModel):
    items: list[HandoverNoteOut]


class HandoverCandidateOut(BaseModel):
    """A colleague a nurse can hand a patient over to.

    Narrower than UserOut on purpose, and for the same reason the pharmacy
    adjustment picker has its own route: GET /users is gated `admin`, so the
    handover form could not list anybody and fell back to asking a nurse to
    paste a user UUID at the end of a shift.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    designation: str | None


class HandoverCandidateListOut(BaseModel):
    items: list[HandoverCandidateOut]

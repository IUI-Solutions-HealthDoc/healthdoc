"""Nursing models — vitals and intake/output (§3 0023), eMAR (§3 0043).

0023 created these tables in July and nothing ever mapped them. `app/nursing/`
held a `/ping` router and nothing else, so the vitals a nurse records had no
way in or out of the system — found in the 2026-08-17 sweep (#390).

Constraint names are passed bare: NAMING_CONVENTION in app/common/db.py renders
`ck` as ck_<table>_<name>, so a pre-prefixed name double-prefixes and stops
matching what the migration created.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric,
    SmallInteger, String, Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.enums import (
    IntakeOutputType,
    MedicationAdministrationStatus,
    NursingShift,
)
from app.common.models import Blame, Timestamps, UUIDPk


class Vitals(Base, UUIDPk, Timestamps, Blame):
    """One measurement set. §3 0023.

    Hangs off EITHER an encounter (OPD) or an admission (IPD), never both and
    never neither — ck_vitals_encounter_or_admission. A patient seen in OPD and
    later admitted therefore has vitals on both sides, so the time-series read
    has to union them rather than filter on one column.
    """

    __tablename__ = "vitals"
    __table_args__ = (
        CheckConstraint(
            "(encounter_id IS NOT NULL AND admission_id IS NULL) OR "
            "(encounter_id IS NULL AND admission_id IS NOT NULL)",
            name="encounter_or_admission"),
        Index("ix_vitals_patient_id_measured_at", "patient_id", "measured_at"),
    )

    encounter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=True)
    admission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)

    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    bmi: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    waist_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    hip_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    whr: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)

    temp_c: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    pulse_bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resp_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bp_systolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bp_diastolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spo2_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pain_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class IntakeOutputRecord(Base, UUIDPk, Timestamps, Blame):
    """Fluid balance, one entry per intake or output event. §3 0023."""

    __tablename__ = "intake_output_records"
    __table_args__ = (
        CheckConstraint(IntakeOutputType.sql_check("entry_type"), name="entry_type"),
        CheckConstraint("volume_ml > 0", name="volume_positive"),
    )

    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(50), nullable=False)

    #: Always positive. Direction comes from entry_type, not from the sign —
    #: a negative "output" and a positive "output" would otherwise both be
    #: representable and mean opposite things.
    volume_ml: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class MedicationAdministration(Base, UUIDPk, Timestamps, Blame):
    """eMAR: what a nurse actually did with one prescribed dose. §3 0043.

    One row per administration *attempt*, not per scheduled dose. The schedule
    is derivable from the prescription's frequency and duration; materialising
    it would put a second source of truth next to the prescription.
    """

    __tablename__ = "medication_administration"
    __table_args__ = (
        CheckConstraint(MedicationAdministrationStatus.sql_check("status"), name="status"),
        # held and refused must say why. An unexplained missed dose is what an
        # adverse-event review cannot reconstruct.
        CheckConstraint(
            "status = 'given' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="reason_required"),
        Index("ix_medication_administration_admission_at", "admission_id", "administered_at"),
        Index("ix_medication_administration_item", "prescription_item_id"),
    )

    prescription_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prescription_items.id", ondelete="RESTRICT"),
        nullable=False)
    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    administered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[str] = mapped_column(String(50), nullable=False)
    dose_given: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class NursingHandoverNote(Base, UUIDPk, Timestamps, Blame):
    """One shift handover, in SBAR. §3 0050.

    The table has existed since 0050 with no model, service or route behind it,
    so the frontend's AddHandoverForm and HandoverNotes were built against an
    API that was never published and the ward could not record a handover at
    all. Shift handover is the point at which responsibility for a patient
    transfers, and NABH asks to see it; an unrecorded transfer is the gap every
    incident review looks for first.

    SBAR rather than a free-text box because that is what the columns already
    are, and because the structure is the safety mechanism: it is what stops a
    handover being "patient in bed 4 is fine".

    `handed_over_to` is the receiving nurse, and is deliberately NOT nullable —
    a handover to nobody is a note, not a handover.
    """

    __tablename__ = "nursing_handover_notes"
    __table_args__ = (
        CheckConstraint(NursingShift.sql_check("shift"), name="shift"),
    )

    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=False)
    shift: Mapped[str] = mapped_column(String(50), nullable=False)
    situation: Mapped[str | None] = mapped_column(Text, nullable=True)
    background: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    handed_over_to: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

"""Emergency triage models (HD-18, migration 0076).

Tracks ED patient arrivals, acuity triage classification (resuscitation,
emergent, urgent, non_urgent), bay and clinician assignment, re-triage audit trail,
and door-to-clinician throughput metrics.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Index, String, Text, func, text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.common.db import Base
from app.common.models import UUIDPk


class EmergencyTriage(Base, UUIDPk):
    """Active ED Triage assessment and tracking record.

    Matches migration 0076_emar_triage_analytes_urgency.py.
    """

    __tablename__ = "emergency_triages"
    __table_args__ = (
        CheckConstraint(
            "acuity_level IN ('resuscitation', 'emergent', 'urgent', 'non_urgent')",
            name="acuity_level",
        ),
        CheckConstraint(
            "status IN ('waiting', 'in_treatment', 'admitted', 'discharged', 'lwbs')",
            name="status",
        ),
        CheckConstraint(
            "disposition IS NULL OR disposition IN ('admit', 'discharge', 'lwbs', 'transfer')",
            name="disposition",
        ),
        Index("ix_emergency_triages_facility_status", "facility_id", "status"),
        Index("ix_emergency_triages_patient", "patient_id"),
        Index("ix_emergency_triages_visit", "visit_id"),
        Index("ix_emergency_triages_assigned_doctor", "assigned_doctor_id"),
        Index("ix_emergency_triages_triaged_by", "triaged_by"),
        Index("ix_emergency_triages_created_by", "created_by"),
        Index("ix_emergency_triages_updated_by", "updated_by"),
    )

    facility_id = Column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    visit_id = Column(
        UUID(as_uuid=True), ForeignKey("visits.id", ondelete="RESTRICT"), nullable=False
    )

    acuity_level = Column(String(30), nullable=False)
    chief_complaint = Column(Text, nullable=False)
    triage_notes = Column(Text, nullable=True)

    assigned_doctor_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    assigned_bay = Column(String(50), nullable=True)
    status = Column(String(30), nullable=False, server_default=text("'waiting'"))

    triaged_at = Column(DateTime(timezone=True), nullable=False)
    triaged_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    clinician_seen_at = Column(DateTime(timezone=True), nullable=True)

    disposition = Column(String(30), nullable=True)
    disposition_at = Column(DateTime(timezone=True), nullable=True)
    disposition_notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )


class EmergencyTriageLog(Base, UUIDPk):
    """Immutable audit trail of acuity re-evaluations with mandatory clinical reasoning."""

    __tablename__ = "emergency_triage_logs"
    __table_args__ = (
        Index("ix_emergency_triage_logs_triage", "triage_id", "changed_at"),
        Index("ix_emergency_triage_logs_changed_by", "changed_by"),
    )

    triage_id = Column(
        UUID(as_uuid=True), ForeignKey("emergency_triages.id", ondelete="CASCADE"), nullable=False
    )
    previous_acuity = Column(String(30), nullable=False)
    new_acuity = Column(String(30), nullable=False)
    reason = Column(Text, nullable=False)
    changed_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

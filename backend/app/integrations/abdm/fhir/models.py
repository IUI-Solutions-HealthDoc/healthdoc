"""schema.md §3, 0026 — Postgres audit of every ABDM transmission.

The payloads (actual FHIR Bundle documents) live in Mongo; this row is the
auditable fact that a transmission happened. That split is deliberate: a
Mongo outage must not lose the record that a transmission was attempted,
and ABDM compliance questions are answered from Postgres, not Mongo.

facility_id is NOT NULL here even though schema.md's own prose table for
this section doesn't list it — the migration (0026_fhir_notifications.py)
is ground truth and does require it. Same lesson as 0034: when the doc and
the migration disagree, trust the migration.
"""
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk


class FhirBundleTransaction(Base, UUIDPk, Timestamps):
    __tablename__ = "fhir_bundle_transactions"

    bundle_id = Column(String(100), nullable=False)
    abdm_request_id = Column(String(100), nullable=True)
    direction = Column(String(30), nullable=False)
    care_context_linked = Column(Boolean, nullable=True)
    gateway_response_status = Column(String(50), nullable=True)
    signed_by_hpr_id = Column(String(50), nullable=True)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=True
    )
    consent_id = Column(
        UUID(as_uuid=True), ForeignKey("consent_records.id", ondelete="RESTRICT"), nullable=True
    )
    transmitted_at = Column(DateTime(timezone=True), nullable=False)
    facility_id = Column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("direction IN ('hip_push','hiu_pull')",
                         name="ck_fhir_bundle_transactions_direction"),
        Index("ix_fhir_bundle_transactions_patient_id", "patient_id", "transmitted_at"),
        Index("ix_fhir_bundle_transactions_facility_id", "facility_id"),
    )

"""FhirBundleTransaction -- Postgres audit fact for FHIR bundle generation /
transmission (schema.md §3, migration 0026). The full bundle payload lives
outside Postgres (projected via the outbox, same as any clinical note --
see service.py's module docstring); this row is the auditable fact that a
bundle was built/transmitted, per §3's "a Mongo outage must not lose the
record that a transmission happened" rule.
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
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=True)
    consent_id = Column(UUID(as_uuid=True), ForeignKey("consent_records.id", ondelete="RESTRICT"), nullable=True)
    transmitted_at = Column(DateTime(timezone=True), nullable=False)
    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False)

    __table_args__ = (
        CheckConstraint("direction IN ('hip_push','hiu_pull')", name="direction"),
        Index("ix_fhir_bundle_transactions_patient_id", "patient_id", "transmitted_at"),
        Index("ix_fhir_bundle_transactions_facility_id", "facility_id"),
    )

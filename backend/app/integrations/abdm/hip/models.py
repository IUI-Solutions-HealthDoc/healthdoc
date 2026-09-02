"""HIP (M2) tables — care contexts, links, notified consents, data requests.

A HIP is the side that HOLDS records and hands them over. Four facts have to be
durable for that to be auditable, and each table here is one of them:

  care contexts        what units of care exist and can be offered
  links                which ABHA address has been allowed to see them
  consent artefacts    what the consent manager told us was permitted
  HI requests          what was asked for, and what we actually sent

`facility_id` is NOT NULL on every one of them. That is not decoration: it is
what makes these rows scopeable by the same `CurrentDbUser` rule as the rest of
the app, and what lets audit_logs.facility_id be satisfied when these models
are opted into the audit listener.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.common.db import Base
from app.common.models import Blame, Timestamps, UUIDPk


class AbdmCareContext(Base, UUIDPk, Timestamps, Blame):
    """One unit of care that can be offered to an ABHA address.

    `reference` is the string ABDM will quote back at us for the rest of time,
    so it is generated once and never recomputed from mutable data. It is
    unique per patient rather than globally: two facilities may legitimately
    both hold a context for the same person.
    """

    __tablename__ = "abdm_care_contexts"

    facility_id = Column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    visit_id = Column(
        UUID(as_uuid=True), ForeignKey("visits.id", ondelete="RESTRICT"), nullable=True
    )

    reference = Column(String(100), nullable=False)
    display = Column(String(200), nullable=False)
    #: ABDM's HI type vocabulary. Constrained because a value outside this set
    #: is silently dropped by the gateway rather than rejected, which presents
    #: later as "the record was shared but the HIU cannot see it".
    hi_type = Column(String(50), nullable=False)

    __audit_resource_type__ = "abdm_care_contexts"
    __audit_facility_id_field__ = "facility_id"
    __audit_patient_id_field__ = "patient_id"

    __table_args__ = (
        UniqueConstraint("patient_id", "reference", name="uq_abdm_care_context_patient_reference"),
        # Narrowed to the types fhir/builder.py can actually populate — see the
        # HI_TYPES note in hip/gateway.py. Migration 0059 narrows the DB CHECK to
        # match; the drift test keeps builder, validator and CHECK in agreement.
        CheckConstraint(
            "hi_type IN ('OPConsultation','Prescription','DiagnosticReport',"
            "'DischargeSummary','WellnessRecord')",
            name="abdm_care_context_hi_type",
        ),
        Index("ix_abdm_care_contexts_facility_id", "facility_id"),
        Index("ix_abdm_care_contexts_patient_id", "patient_id"),
        # Every FK gets a leading index — the convention
        # test_every_foreign_key_has_a_leading_non_partial_index enforces.
        # Unindexed FKs make the parent's DELETE/UPDATE scan the child table
        # while holding a lock, which is how a routine patient merge turns
        # into a stall.
        Index("ix_abdm_care_contexts_visit_id", "visit_id"),
        Index("ix_abdm_care_contexts_created_by", "created_by"),
        Index("ix_abdm_care_contexts_updated_by", "updated_by"),
    )


class AbdmCareContextLink(Base, UUIDPk, Timestamps):
    """An ABHA address's claim on this facility's care contexts.

    No `Blame`. A link is created either by staff (HIP-initiated) or by the
    patient through their ABHA app, which reaches us as a gateway callback with
    no local user at all. A NOT NULL created_by would make the second case
    impossible to record, and inventing a system user to satisfy it would put a
    fictional actor in the audit trail. Who initiated a link is answered by
    audit_logs, which this model opts into.

    Status is a real state machine and the CHECK enforces it, because a link
    that is `pending` and a link that is `confirmed` differ by whether we may
    hand over records — the most consequential boolean in the module.
    """

    __tablename__ = "abdm_care_context_links"

    facility_id = Column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )

    abha_address = Column(String(120), nullable=False)
    link_ref_number = Column(String(120), nullable=True)
    gateway_request_id = Column(String(100), nullable=True)
    transaction_id = Column(String(120), nullable=True)
    care_context_references = Column(JSONB, nullable=False, server_default="[]")
    status = Column(String(50), nullable=False, server_default="pending")
    #: Why a link failed, for the desk. Never carries a gateway body verbatim —
    #: those echo identifiers we just sent.
    failure_reason = Column(Text, nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    __audit_resource_type__ = "abdm_care_context_links"
    __audit_facility_id_field__ = "facility_id"
    __audit_patient_id_field__ = "patient_id"

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','confirmed','failed','expired')", name="abdm_link_status"
        ),
        Index("ix_abdm_links_facility_id", "facility_id"),
        Index("ix_abdm_links_abha_address", "abha_address"),
        Index("ix_abdm_links_ref", "link_ref_number"),
        Index("ix_abdm_links_transaction", "transaction_id"),
        Index("ix_abdm_links_patient_id", "patient_id"),
    )


class AbdmHipConsentArtefact(Base, UUIDPk, Timestamps):
    """A consent the manager told us about, stored as it arrived.

    `raw_artefact` keeps the gateway's own JSON. That is deliberate duplication
    of the parsed columns beside it: when an assessor asks "on what basis did
    you release this record", the answer has to be the document we were given,
    not our reading of it. The parsed columns are for querying; the raw blob is
    the evidence.

    No patient_id FK. The consent manager identifies people by ABHA address and
    we may be notified about someone before they exist locally; resolving that
    to a patient row is the service's job and it may legitimately fail.
    """

    __tablename__ = "abdm_hip_consent_artefacts"

    facility_id = Column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    consent_artefact_id = Column(String(120), nullable=False)
    abha_address = Column(String(120), nullable=False)
    status = Column(String(50), nullable=False, server_default="granted")

    hi_types = Column(JSONB, nullable=False)
    date_range_from = Column(DateTime(timezone=True), nullable=True)
    date_range_to = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    raw_artefact = Column(JSONB, nullable=False)

    __audit_resource_type__ = "abdm_hip_consent_artefacts"
    __audit_facility_id_field__ = "facility_id"

    __table_args__ = (
        UniqueConstraint("consent_artefact_id", name="uq_abdm_hip_artefact_id"),
        CheckConstraint(
            "status IN ('granted','revoked','expired')", name="abdm_hip_artefact_status"
        ),
        Index("ix_abdm_hip_artefacts_facility_id", "facility_id"),
        Index("ix_abdm_hip_artefacts_abha", "abha_address"),
    )


class AbdmHipHealthInformationRequest(Base, UUIDPk, Timestamps):
    """A request for data, and the record of what we did about it.

    `hiu_key_material` holds the HIU's PUBLIC half only. There is no private
    key column on this table and there must never be one — the HIP generates
    its keypair inside the push and discards it (see hi_crypto.py).
    """

    __tablename__ = "abdm_hip_hi_requests"

    facility_id = Column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    consent_artefact_id = Column(String(120), nullable=False)
    transaction_id = Column(String(120), nullable=False)
    gateway_request_id = Column(String(100), nullable=True)

    hiu_key_material = Column(JSONB, nullable=False)
    data_push_url = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, server_default="received")
    bundles_sent = Column(String(10), nullable=True)
    failure_reason = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __audit_resource_type__ = "abdm_hip_hi_requests"
    __audit_facility_id_field__ = "facility_id"

    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_abdm_hip_hi_transaction"),
        CheckConstraint(
            "status IN ('received','refused','transferring','delivered','failed')",
            name="abdm_hip_hi_status",
        ),
        Index("ix_abdm_hip_hi_facility_id", "facility_id"),
    )

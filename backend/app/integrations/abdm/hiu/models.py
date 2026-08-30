"""HIU (M3) tables — consent requests, granted artefacts, data requests, receipts.

A HIU is the side that ASKS for records it does not hold. The auditable chain
is: we asked (consent request) → the patient allowed it (artefact) → we
requested data under it (HI request) → data arrived (receipt). Breaking any
link in that chain is what an assessor is looking for, so each is its own row
with its own timestamps rather than status flags on one wide table.
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.common.db import Base
from app.common.models import Blame, Timestamps, UUIDPk


class AbdmConsentRequest(Base, UUIDPk, Timestamps, Blame):
    """A request we made to the consent manager on a patient's behalf."""

    __tablename__ = "abdm_consent_requests"

    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=True)

    abha_address = Column(String(120), nullable=False)
    purpose_code = Column(String(50), nullable=False)
    hi_types = Column(JSONB, nullable=False)
    date_range_from = Column(DateTime(timezone=True), nullable=False)
    date_range_to = Column(DateTime(timezone=True), nullable=False)
    #: How long WE asked to keep it. The manager may return less; the artefact
    #: is what binds, not this.
    requested_expiry = Column(DateTime(timezone=True), nullable=False)

    consent_request_id = Column(String(120), nullable=True)
    gateway_request_id = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False, server_default="requested")
    failure_reason = Column(Text, nullable=True)

    __audit_resource_type__ = "abdm_consent_requests"
    __audit_facility_id_field__ = "facility_id"
    __audit_patient_id_field__ = "patient_id"

    __table_args__ = (
        CheckConstraint(
            "status IN ('requested','granted','denied','expired','revoked','failed')",
            name="abdm_consent_request_status",
        ),
        CheckConstraint("date_range_to >= date_range_from", name="abdm_consent_request_range"),
        Index("ix_abdm_consent_requests_facility_id", "facility_id"),
        Index("ix_abdm_consent_requests_abha", "abha_address"),
        Index("ix_abdm_consent_requests_patient_id", "patient_id"),
        Index("ix_abdm_consent_requests_created_by", "created_by"),
        Index("ix_abdm_consent_requests_updated_by", "updated_by"),
    )


class AbdmHiuConsentArtefact(Base, UUIDPk, Timestamps):
    """A granted artefact, kept verbatim beside its parsed fields.

    Same reasoning as the HIP side: the raw document is the evidence for why we
    were allowed to hold someone's records, and our parse of it is not.
    """

    __tablename__ = "abdm_hiu_consent_artefacts"

    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False)
    consent_request_id = Column(
        UUID(as_uuid=True), ForeignKey("abdm_consent_requests.id", ondelete="RESTRICT"), nullable=False
    )

    consent_artefact_id = Column(String(120), nullable=False)
    status = Column(String(50), nullable=False, server_default="granted")
    hi_types = Column(JSONB, nullable=False)
    date_range_from = Column(DateTime(timezone=True), nullable=True)
    date_range_to = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    raw_artefact = Column(JSONB, nullable=False)

    __audit_resource_type__ = "abdm_hiu_consent_artefacts"
    __audit_facility_id_field__ = "facility_id"

    __table_args__ = (
        UniqueConstraint("consent_artefact_id", name="uq_abdm_hiu_artefact_id"),
        CheckConstraint("status IN ('granted','revoked','expired')", name="abdm_hiu_artefact_status"),
        Index("ix_abdm_hiu_artefacts_facility_id", "facility_id"),
        Index("ix_abdm_hiu_artefacts_request", "consent_request_id"),
    )


class AbdmHiuHealthInformationRequest(Base, UUIDPk, Timestamps, Blame):
    """A data request, and the ephemeral key material that will open the reply.

    THE PRIVATE KEY COLUMN
    ----------------------
    `private_key_encrypted` is the one place in this integration where a
    private key is written down, and it is here because the exchange is
    asynchronous: we publish a public key, and a HIP pushes data against it
    minutes or hours later, quite possibly into a different process than the
    one that asked. Holding the key in memory would lose every in-flight
    request on a deploy.

    It is stored through common/security.py — AES-GCM, key-versioned, the same
    path as Aadhaar — never in plaintext, and `key_version` is recorded so a
    key rotation can still open an in-flight transfer. `clear_private_key()`
    is what runs when the transfer finishes: a key that can no longer open
    anything should not still be sitting in a row.
    """

    __tablename__ = "abdm_hiu_hi_requests"

    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False)
    artefact_id = Column(
        UUID(as_uuid=True), ForeignKey("abdm_hiu_consent_artefacts.id", ondelete="RESTRICT"), nullable=False
    )

    transaction_id = Column(String(120), nullable=True)
    gateway_request_id = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False, server_default="requested")
    failure_reason = Column(Text, nullable=True)

    #: OUR half. Public parts are sent to the gateway; the private key is
    #: encrypted at rest and cleared on completion.
    public_key_b64 = Column(Text, nullable=False)
    nonce_b64 = Column(Text, nullable=False)
    private_key_encrypted = Column(LargeBinary, nullable=True)
    key_version = Column(SmallInteger, nullable=True)
    key_expires_at = Column(DateTime(timezone=True), nullable=False)

    __audit_resource_type__ = "abdm_hiu_hi_requests"
    __audit_facility_id_field__ = "facility_id"
    #: Key material never reaches audit_logs. listeners.py would otherwise
    #: record the ciphertext as a changed column, and audit_logs is append-only
    #: — so clearing the key from this row on completion would leave a copy
    #: behind that nothing can remove. That is the exact opposite of what
    #: clear_private_key() exists to achieve.
    #:
    #: The public half is deliberately NOT excluded: which public key we
    #: published is a legitimate part of the trail.
    __audit_exclude_fields__ = ("private_key_encrypted", "key_version")

    __table_args__ = (
        CheckConstraint(
            "status IN ('requested','acknowledged','received','partial','failed','expired')",
            name="abdm_hiu_hi_status",
        ),
        # A cleared key must clear its version with it. Two columns describing
        # one fact drift apart otherwise, and "which key opened this" becomes
        # unanswerable at exactly the moment someone asks.
        CheckConstraint(
            "(private_key_encrypted IS NULL) = (key_version IS NULL)",
            name="abdm_hiu_hi_key_pair_consistent",
        ),
        Index("ix_abdm_hiu_hi_facility_id", "facility_id"),
        Index("ix_abdm_hiu_hi_transaction", "transaction_id"),
        Index("ix_abdm_hiu_hi_artefact_id", "artefact_id"),
        Index("ix_abdm_hiu_hi_created_by", "created_by"),
        Index("ix_abdm_hiu_hi_updated_by", "updated_by"),
    )


class AbdmReceivedBundle(Base, UUIDPk, Timestamps):
    """One care context's worth of data that arrived from a HIP.

    The decrypted bundle is NOT stored here. It goes to the same outbox path
    every other clinical document takes, and this row is the durable fact that
    it arrived — the pattern fhir/models.py already set, and for the same
    reason: a Mongo outage must not lose the record that a transfer happened.
    """

    __tablename__ = "abdm_received_bundles"

    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False)
    hi_request_id = Column(
        UUID(as_uuid=True), ForeignKey("abdm_hiu_hi_requests.id", ondelete="RESTRICT"), nullable=False
    )

    care_context_reference = Column(String(120), nullable=True)
    #: sha256 of the DECRYPTED bundle. Lets a later reader prove the document
    #: they are looking at is the one that arrived, without this table holding
    #: the clinical content itself.
    content_sha256 = Column(String(64), nullable=False)
    status = Column(String(50), nullable=False, server_default="stored")
    failure_reason = Column(Text, nullable=True)

    __audit_resource_type__ = "abdm_received_bundles"
    __audit_facility_id_field__ = "facility_id"

    __table_args__ = (
        CheckConstraint("status IN ('stored','undecipherable','rejected')", name="abdm_received_bundle_status"),
        Index("ix_abdm_received_bundles_facility_id", "facility_id"),
        Index("ix_abdm_received_bundles_request", "hi_request_id"),
    )

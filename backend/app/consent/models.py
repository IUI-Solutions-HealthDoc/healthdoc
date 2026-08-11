"""
SQLAlchemy models for the consent module.

Repo path: backend/app/consent/models.py

Table shapes here must match migration 0004
(backend/migrations/versions/0004_consent.py) exactly — that migration is
the source of truth for DDL (raw SQL for the partitioned data_access_log
table, ordinary op.create_table for the rest). This file only describes
shape for ORM querying. Never call Base.metadata.create_all() for
data_access_log — migrations only (repo rule), same reasoning as audit_logs.

patient_id / visit_id are plain UUID columns with NO ForeignKey() here —
patients and visits don't exist as tables yet (they land in migrations
0006/0007). Those FK constraints get added later via ALTER TABLE, inside
those migrations, same pattern as audit_logs.patient_id / visit_id.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Blame, Timestamps, UUIDPk


class ConsentPurpose(UUIDPk, Timestamps, Base):
    """Catalog of reasons the hospital ever asks a patient for consent."""

    __tablename__ = "consent_purposes"

    purpose_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_expiry_days: Mapped[int | None] = mapped_column(nullable=True)
    requires_explicit_consent: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ConsentPurpose id={self.id} code={self.purpose_code}>"


class ConsentRecord(UUIDPk, Blame, Timestamps, Base):
    """
    One row per patient consent grant.

    Immutable after insert except `status` / `status_changed_at` (repo
    convention, enforced at the service layer — same repo rule as audit:
    the status flip and any related insert, e.g. a ConsentWithdrawal row,
    must happen in the SAME transaction).
    """

    __tablename__ = "consent_records"

    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)  # FK added in 0006
    visit_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # FK added in 0007

    purpose_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consent_purposes.id", ondelete="RESTRICT", name="fk_consent_records_purpose_id"),
        nullable=False,
    )

    granted_by_type: Mapped[str] = mapped_column(String(50), nullable=False)  # GrantedByType enum
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_consent_records_granted_by_user_id"),
        nullable=True,
    )
    guardian_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    guardian_relationship: Mapped[str | None] = mapped_column(String(50), nullable=True)
    guardian_id_proof_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # FK added in 0019

    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # NULLABLE per issue spec
    scope: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)  # ConsentChannel enum
    consent_artefact_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_artefact_signature: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="granted")  # ConsentStatus enum
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_consent_records_patient_id", "patient_id"),
        Index("ix_consent_records_purpose_id", "purpose_id"),
        Index("ix_consent_records_granted_by_user_id", "granted_by_user_id"),
        Index("ix_consent_records_created_by", "created_by"),
        Index("ix_consent_records_updated_by", "updated_by"),
        CheckConstraint(
            "granted_by_type IN ('patient', 'guardian', 'nominee')",
            name="granted_by_type",
        ),
        CheckConstraint(
            "channel IN ('verbal', 'written', 'digital_otp', 'abdm_consent_manager')",
            name="channel",
        ),
        CheckConstraint(
            "status IN ('requested', 'granted', 'denied', 'revoked', 'expired')",
            name="status",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ConsentRecord id={self.id} patient={self.patient_id} status={self.status}>"


class ConsentWithdrawal(UUIDPk, Base):
    """
    Append-only. Inserting a row here should, in the same transaction,
    flip the parent ConsentRecord.status to 'revoked'.

    withdrawn_by_type includes 'system_expiry' (an automated expiry sweep),
    which is why it uses a literal CHECK instead of a CheckedEnum from
    enums.py — no GrantedByType-style class covers this fourth value.
    """

    __tablename__ = "consent_withdrawals"

    consent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consent_records.id", ondelete="RESTRICT", name="fk_consent_withdrawals_consent_id"),
        nullable=False,
    )
    withdrawn_by_type: Mapped[str] = mapped_column(String(50), nullable=False)
    withdrawn_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_consent_withdrawals_withdrawn_by_user_id"),
        nullable=True,
    )
    withdrawn_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cascaded_actions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cascade_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cascade_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_consent_withdrawals_consent_id", "consent_id"),
        Index("ix_consent_withdrawals_withdrawn_by_user_id", "withdrawn_by_user_id"),
        CheckConstraint(
            "withdrawn_by_type IN ('patient', 'guardian', 'nominee', 'system_expiry')",
            name="withdrawn_by_type",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ConsentWithdrawal id={self.id} consent={self.consent_id}>"


class DataAccessLog(UUIDPk, Base):
    """
    Append-only, hash-free, monthly-partitioned by accessed_at — same
    partitioning/append-only pattern as AuditLog, minus the hash chain
    (no prev_hash/entry_hash/signature columns exist for this table).

    Composite PK (id, accessed_at) — Postgres partitioned tables must
    include the partition key in every unique/primary key.

    Never call Base.metadata.create_all() for this table — migration
    0004 owns its DDL (raw SQL, same reasoning as audit_logs).
    """

    __tablename__ = "data_access_log"

    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now(), nullable=False
    )

    consent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consent_records.id", ondelete="RESTRICT", name="fk_data_access_log_consent_id"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_data_access_log_user_id"),
        nullable=False,
    )
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # FK added in 0006
    purpose_code: Mapped[str | None] = mapped_column(String(50), nullable=True)

    access_channel: Mapped[str] = mapped_column(String(50), nullable=False)  # AccessChannel enum
    emergency_access: Mapped[bool] = mapped_column(nullable=False, server_default="false")  # break-glass flag
    consent_required: Mapped[bool | None] = mapped_column(nullable=True)
    consent_verified: Mapped[bool | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_data_access_log_user_id", "user_id", "accessed_at"),
        Index("ix_data_access_log_patient_id", "patient_id", "accessed_at"),
        Index("ix_data_access_log_consent_id", "consent_id"),
        CheckConstraint(
            "access_channel IN ('ui', 'api', 'abdm_hiu', 'export')",
            name="access_channel",
        ),
        {"postgresql_partition_by": "RANGE (accessed_at)"},
    )
    # NOTE: BRIN index on accessed_at (ix_data_access_log_accessed_at_brin,
    # per the index strategy addendum) is created in the migration only —
    # same reasoning as audit_logs' BRIN index.

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DataAccessLog id={self.id} user={self.user_id} resource={self.resource_type}:{self.resource_id}>"


class BreakGlassGrant(UUIDPk, Timestamps, Base):
    """
    Emergency ("break-glass") access grant — added to the schema doc in
    v3.9, under migration 0004 (this module's own migration). Was missing
    from this file/migration entirely; added per the v3.13 schema pass.

    A grant is active iff `now() < expires_at AND revoked_at IS NULL`
    (app/service-layer check — no DB constraint can express "now()" at
    read time). Clinical reads consult this table when consent is absent;
    every read under an active grant still writes a DataAccessLog row
    with emergency_access=True (see app/consent/access_log.py).

    expires_at is NOT server-computed here — the service sets it to
    granted_at + <facility-configurable window, default 2h> at insert
    time, since the window is a facility setting, not a fixed interval.

    Unreviewed expired grants (reviewed_at IS NULL and expires_at is in
    the past) are the DPO/compliance queue's worklist — that queue reads
    this table directly; no separate table backs it.
    """

    __tablename__ = "break_glass_grants"

    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)  # FK added in 0006
    granted_to_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_break_glass_grants_granted_to_user_id"),
        nullable=False,
    )
    justification: Mapped[str] = mapped_column(Text, nullable=False)  # >= 20 chars, enforced at service layer
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # granted_at + facility-configurable window

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_break_glass_grants_revoked_by"),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_break_glass_grants_reviewed_by"),
        nullable=True,
    )
    review_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_break_glass_grants_patient_id", "patient_id", "expires_at"),
        Index("ix_break_glass_grants_granted_to_user_id", "granted_to_user_id", "expires_at"),
        Index("ix_break_glass_grants_revoked_by", "revoked_by"),
        Index("ix_break_glass_grants_reviewed_by", "reviewed_by"),
        CheckConstraint(
            "char_length(justification) >= 20",
            name="justification_length",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BreakGlassGrant id={self.id} patient={self.patient_id} expires_at={self.expires_at}>"


class ConsentRenewalReminder(UUIDPk, Base):
    """A queued reminder that a consent is approaching its expires_at."""

    __tablename__ = "consent_renewal_reminders"

    consent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consent_records.id", ondelete="RESTRICT", name="fk_consent_renewal_reminders_consent_id"),
        nullable=False,
    )
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_channel: Mapped[str | None] = mapped_column(String(50), nullable=True)  # blanket enum-width rule -> 50
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_consent_renewal_reminders_consent_id", "consent_id"),
        Index("ix_consent_renewal_reminders_remind_at", "remind_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ConsentRenewalReminder id={self.id} consent={self.consent_id} remind_at={self.remind_at}>"

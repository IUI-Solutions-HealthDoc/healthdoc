"""
SQLAlchemy models for the audit module.

Repo path: backend/app/audit/models.py

`audit_logs` is monthly-partitioned, append-only, and hash-chained at the
DATABASE level — partitioning + both triggers live as raw SQL in migration
0003 (backend/migrations/versions/0003_audit.py), because Alembic
autogenerate cannot produce `PARTITION BY RANGE` or trigger DDL. This file
only describes the table's shape so the app can query/insert through the
ORM. Never call Base.metadata.create_all() for this table — migrations
only (repo rule), and create_all() wouldn't know how to partition it
anyway.

department_id, patient_id, and visit_id are plain UUID columns with NO
ForeignKey() here. departments/patients/visits don't exist as tables yet
(they land in migrations 0005/0006/0007) — you cannot reference a table
that doesn't exist, Postgres would reject the CREATE TABLE outright. Those
FK constraints get added later via ALTER TABLE, inside those migrations.
facility_id and user_id DO get real ForeignKey()s below, since facilities
and users are real as of migration 0002.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import CHAR, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk


class AuditLog(UUIDPk, Base):
    """
    Append-only, hash-chained, monthly-partitioned audit trail.

    Composite PK (id, created_at) — Postgres partitioned tables must
    include the partition key in every unique/primary key. UUIDPk gives us
    `id`; `created_at` is declared here with primary_key=True to complete
    the pair. Deliberately NOT using the Timestamps mixin — this table has
    no `updated_at` (append-only tables never get one, per schema doc).

    Chaining is asynchronous and per-facility (schema doc §3 0003, post
    review). The row is written with `chain_seq` only — assigned
    gaplessly by the BEFORE INSERT trigger
    `trg_audit_logs_assign_chain_seq` from a row in `audit_counters`
    (never a raw Postgres SEQUENCE — sequences aren't transactional, so
    a rolled-back insert still consumes a number and leaves a gap that
    looks identical to a deleted row; a counter row incremented inside
    the same transaction has no such gap, so any gap the sealer finds
    is unambiguous tampering evidence). `prev_hash`, `entry_hash`,
    `signature`, and `signer_key_id` are all NULL at insert time; a
    separate single-threaded per-facility sealer job fills them in
    afterwards, walking rows in chain_seq order. `sealed_at` NULL
    means "not yet chained" (an alert if older than the 15-minute SLA).
    Do NOT set any of prev_hash/entry_hash/signature/signer_key_id/
    sealed_at from application code — the write path only ever supplies
    the business columns.

    Every write to this table must happen in the SAME transaction as the
    mutation it's recording (repo rule) — e.g. wrap the patient update and
    the AuditLog insert in one session.commit().

    v3.4.1 policy: no table may FK to audit_logs.id (its PK is partitioned
    and old partitions get archived) — other modules must reference audit
    rows by value, never by FK. Nothing here changes because of this; it's
    a constraint on other developers' future tables, not this one.
    """

    __tablename__ = "audit_logs"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now(), nullable=False
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="RESTRICT", name="fk_audit_logs_facility_id"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_audit_logs_user_id"),
        nullable=True,
    )
    role: Mapped[str | None] = mapped_column(nullable=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # FK added in 0005
    action: Mapped[str] = mapped_column(nullable=False)  # create | update | merge | login | ...
    resource_type: Mapped[str] = mapped_column(nullable=False)  # table/module name
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # FK added in 0006
    visit_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # FK added in 0007
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    device_id: Mapped[str | None] = mapped_column(nullable=True)

    # Per-facility monotonic write order (trigger-assigned). This is what
    # the async sealer walks in order — see class docstring.
    chain_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # All five below are NULL until the sealer job runs.
    prev_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)  # sealer-computed
    signature: Mapped[str | None] = mapped_column(nullable=True)  # sealer-computed (Ed25519)
    signer_key_id: Mapped[str | None] = mapped_column(nullable=True)  # sealer-computed
    sealed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # NULL = not yet chained

    __table_args__ = (
        Index("ix_audit_logs_user_id", "user_id", "created_at"),
        Index("ix_audit_logs_patient_id", "patient_id", "created_at"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        # created_at is appended only because Postgres requires a
        # partitioned table's unique constraints to include the
        # partition key — the logical constraint is (facility_id,
        # chain_seq), per schema doc §3 0003.
        UniqueConstraint(
            "facility_id", "chain_seq", "created_at", name="uq_audit_logs_facility_chain_seq"
        ),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )
    # NOTE: a BRIN index on created_at (ix_audit_logs_created_at_brin, per
    # the v3.3 index strategy addendum) is created in the migration only —
    # BRIN isn't declared here since this table's whole DDL lives in raw
    # SQL for consistency (see module docstring above).

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog id={self.id} action={self.action} resource={self.resource_type}:{self.resource_id}>"


class AuditCounter(Base):
    """
    Gapless per-facility allocator for `audit_logs.chain_seq` — same
    pattern as `billing_counters`. Row is upserted on first audit write
    for a facility by the `trg_audit_logs_assign_chain_seq` trigger
    (migration 0003); this ORM class exists mainly so tests and any
    future facility-creation code can read/seed it directly, not
    because application code should increment it (the trigger owns
    that, inside the same transaction as the audit insert).

    No `id`/`created_at`/`updated_at` — `facility_id` IS the primary
    key, one row per facility, and there's no meaningful "when was this
    row created" beyond "whenever the first audit event for this
    facility happened."
    """

    __tablename__ = "audit_counters"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="RESTRICT", name="fk_audit_counters_facility_id"),
        primary_key=True,
    )
    last_value: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditCounter facility_id={self.facility_id} last_value={self.last_value}>"


class AuditLogArchive(UUIDPk, Timestamps, Base):
    """
    [no Blame] — record of a monthly audit_logs partition moved to object storage.

    Nullability note: only facility_id and partition_name are required at
    row-creation time (you know which partition you're archiving before
    the job finishes). Everything else (object_storage_bucket/key,
    archive_file_hash, row_count, archived_at, verified_at) fills in
    progressively as the archive job runs — the schema doc doesn't mark
    these NOT NULL, which matches that workflow. Flag this interpretation
    in your PR in case Tech Lead intended stricter constraints.
    """

    __tablename__ = "audit_log_archive"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="RESTRICT", name="fk_audit_log_archive_facility_id"),
        nullable=False,
    )
    partition_name: Mapped[str] = mapped_column(nullable=False)
    period_start: Mapped[date | None] = mapped_column(nullable=True)
    period_end: Mapped[date | None] = mapped_column(nullable=True)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    object_storage_bucket: Mapped[str | None] = mapped_column(nullable=True)
    object_storage_key: Mapped[str | None] = mapped_column(nullable=True)
    archive_file_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # v3.4.1: enum/status columns are varchar(50) — overrides any narrower
    # width shown inline in the schema doc for this column.
    verification_status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pending")

    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('pending', 'verified', 'failed')",
            name="ck_audit_log_archive_verification_status",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLogArchive id={self.id} partition={self.partition_name}>"


class AuditIntegrityCheck(UUIDPk, Timestamps, Base):
    """Result of a periodic job that re-walks a partition's hash chain and verifies signatures."""

    __tablename__ = "audit_integrity_checks"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="RESTRICT", name="fk_audit_integrity_checks_facility_id"),
        nullable=False,
    )
    partition_name: Mapped[str] = mapped_column(nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rows_checked: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chain_valid: Mapped[bool] = mapped_column(nullable=False)
    signatures_valid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    signatures_invalid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_mismatch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    alerted: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AuditIntegrityCheck id={self.id} partition={self.partition_name} "
            f"chain_valid={self.chain_valid}>"
        )

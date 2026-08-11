"""
SQLAlchemy models for the files module.

Repo path: backend/app/files/models.py

Table shapes here must match migration 0019
(backend/migrations/versions/0019_files.py) exactly.

patient_id gets a REAL ForeignKey here — patients (migration 0006) sits
earlier in the chain by number, so no need to defer it. uploaded_by and
facility_id are real too, same reasoning.

Migration 0019 ALSO wires up three FK constraints onto EARLIER tables
now that files finally exists: patients.photo_file_id,
consent_records.guardian_id_proof_file_id, and
order_external_results.result_file_id all start pointing at files.id.
That ALTER TABLE work lives in the migration file, not here — this file
only describes the two new tables.

--- Round-2 fixes, PR #279 review (solutionsiui) ---

Applied:
  1. (blocker) file_access_log.accessed_at is now explicit
     DateTime(timezone=True). The bare `datetime` annotation was
     inferring a naive column while the migration's column is
     TIMESTAMP WITH TIME ZONE — every comparison in Python was
     silently off by the facility's UTC offset.
  2. (blocker) sensitivity / owner_module / action widened
     varchar(30) -> varchar(50) per the v3.4.1 blanket width rule.
     action's CheckConstraint was already built from
     FileAction.sql_check("action") in this file — that part of
     blocker 2 was already correct here; only the migration's
     hardcoded list needed the matching fix (see migration file).
  3. (should-fix) files.facility_id added, NOT NULL, FK ->
     facilities.id RESTRICT — patient photos and guardian ID proofs
     are among the most sensitive rows in the system and had nothing
     scoping them to a facility.
  4. (should-fix) files.sha256 is now NOT NULL — an optional hash
     can't verify the MinIO object still matches what was uploaded,
     so tampering/corruption would be silently undetectable. Must be
     computed at upload time in the service layer.

Resolved — was correctly blocked on another module's file:
  3. scan_status now has its CHECK, generated from
     ScanStatus.sql_check(). The round-2 review claimed ScanStatus was
     already in app/common/enums.py; it wasn't, and the grep in this
     PR's thread proved it. Refusing to edit a CODEOWNERS-assigned file
     and flagging it back was the right call. ScanStatus landed
     separately in #326 and the constraint was added here by the
     reviewer rather than costing another round trip.

Not touched (per review, tracked separately, not this PR):
  - file_access_log.file_id ondelete=RESTRICT vs DPDP erasure conflict.
  - No retention/cleanup path for orphaned MinIO objects on delete.
  - file_access_log not partitioned (Tech Lead's call, not mine).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import CHAR, INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.enums import FileAction, ScanStatus
from app.common.models import Timestamps, UUIDPk


class FileRecord(UUIDPk, Timestamps, Base):
    """
    One row per uploaded file. The actual bytes live in MinIO — this row
    only stores where to find them (bucket + object_key) and who
    uploaded it. Never serve files directly off this table; always
    through a short-lived presigned URL endpoint (per schema doc §7).
    """

    __tablename__ = "files"

    bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)  # MinIO location
    original_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # NOT NULL — round-2 should-fix (was nullable). Compute on upload;
    # without a hash the row can't prove the MinIO object hasn't changed.
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    owner_module: Mapped[str | None] = mapped_column(String(50), nullable=True)  # widened 30->50

    # NEW — round-2 should-fix. Every other sensitive table in this repo
    # scopes to a facility; files had nothing, and patient photos /
    # guardian ID proofs are about as sensitive as rows get.
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="RESTRICT", name="fk_files_facility_id"),
        nullable=False,
    )
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="RESTRICT", name="fk_files_patient_id"),
        nullable=True,
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_files_uploaded_by"),
        nullable=False,
    )
    sensitivity: Mapped[str] = mapped_column(String(50), nullable=False, server_default="normal")  # widened 30->50
    scan_status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="skipped")
    # ^ §4A.4: no malware scanner wired up for MVP. This column exists so the gap
    # is visible on every row ('skipped') instead of implied by silence.

    __table_args__ = (
        Index("ix_files_facility_id", "facility_id"),
        Index("ix_files_patient_id", "patient_id"),
        Index("ix_files_uploaded_by", "uploaded_by"),
        UniqueConstraint("bucket", "object_key", name="uq_files_bucket_object_key"),
        # Generated from the enum, same as action's CHECK below — without it
        # the column accepts any string, so a future scanner integration could
        # write 'clean' from a path that never actually scanned.
        CheckConstraint(ScanStatus.sql_check("scan_status"), name="scan_status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FileRecord id={self.id} bucket={self.bucket} key={self.object_key}>"


class FileAccessLog(UUIDPk, Base):
    """
    Append-only: every view/download/upload/delete-attempt on a file
    writes one row here that can never be changed or removed afterward.

    No Timestamps mixin here on purpose — accessed_at already IS this
    row's event timestamp, and an append-only row with an updated_at
    that can never legitimately change would be misleading. Same
    judgment call made for consent_withdrawals in migration 0004.
    """

    __tablename__ = "file_access_log"

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="RESTRICT", name="fk_file_access_log_file_id"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_file_access_log_user_id"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # widened 30->50; view|download|upload|delete_attempt
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)

    # Round-2 fix (blocker 1): explicit DateTime(timezone=True). Without
    # it SQLAlchemy infers a naive DateTime from the bare `datetime`
    # annotation while the DB column is TIMESTAMPTZ — the ORM hands back
    # a naive value that's silently wrong by the facility's UTC offset.
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_file_access_log_file_id", "file_id"),
        Index("ix_file_access_log_user_id", "user_id"),
        # Already correct pre-round-2 — built from FileAction.sql_check(),
        # not a hardcoded list. Kept as-is.
        CheckConstraint(
            FileAction.sql_check("action"),
            name="action",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FileAccessLog id={self.id} file={self.file_id} action={self.action}>"

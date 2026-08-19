"""Patient models — see docs/database-schema.md §3 (0006) and docs/schema-conventions.md."""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey,
    LargeBinary, SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import UUIDPk, Timestamps, Blame, Versioned
from app.common.enums import (
    GuardianVerificationMethod, IdentifierType, IdentityPath, IdentityStatus,
    MergeSourceType, MergeStatus, PatientStatus, Sex,
)


class Patient(Base, UUIDPk, Timestamps, Blame, Versioned):
    __tablename__ = "patients"
    __table_args__ = (
        # Short names here — app.common.db's NAMING_CONVENTION auto-prefixes
        # every CheckConstraint as ck_<table>_<name> (see db.py). Passing the
        # already-prefixed form double-prefixes it (ck_patients_ck_patients_
        # status), which stops matching what migration 0037 actually named
        # the constraint in the database. This bit us once already — see
        # PR review discussion on constraint naming.
        CheckConstraint("dob IS NOT NULL OR age_years IS NOT NULL", name="dob_or_age"),
        CheckConstraint("uhid IS NOT NULL OR thid IS NOT NULL", name="has_identifier"),
        CheckConstraint(Sex.sql_check("sex"), name="sex"),
        CheckConstraint(IdentityPath.sql_check("identity_path"), name="identity_path"),
        CheckConstraint(IdentityStatus.sql_check("identity_status"), name="identity_status"),
        CheckConstraint(PatientStatus.sql_check("status"), name="status"),
        # Added with 0042. GuardianVerificationMethod already existed in
        # common/enums.py with nothing enforcing it.
        CheckConstraint(
            "guardian_verification_method IS NULL OR "
            + GuardianVerificationMethod.sql_check("guardian_verification_method"),
            name="guardian_verification_method",
        ),
    )

    uhid: Mapped[str | None] = mapped_column(String(30), nullable=True)  # unique via partial index
    thid: Mapped[str | None] = mapped_column(String(25), unique=True, nullable=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    sex: Mapped[str] = mapped_column(String(50), nullable=False)
    dob: Mapped[date | None] = mapped_column(Date, nullable=True)
    age_years: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    guardian_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    guardian_relationship: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)

    address_line: Mapped[str | None] = mapped_column(Text, nullable=True)
    village_town: Mapped[str | None] = mapped_column(Text, nullable=True)
    district: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(5), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(6), nullable=True)

    photo_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # FK to files added in 0019
    abha_number: Mapped[str | None] = mapped_column(String(17), unique=True, nullable=True)

    # 0030 — ABHA linking token (B1). Encrypted same scheme as patient_identifiers.
    abha_linking_token_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    abha_linking_key_version: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    abha_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 0042 — guardian verification (B2). The comment here said 0022 for months;
    # no migration created these columns until 0042, so every ORM INSERT into
    # patients failed against a migrated database while passing in tests, which
    # build their schema from Base.metadata. Found by #393's concurrency test.
    #
    # varchar(30) per §3, not 50 — the widest permitted value is
    # 'manual_document'. The CHECKs live in 0042; names are passed bare because
    # NAMING_CONVENTION prefixes them (a pre-prefixed name double-prefixes).
    is_minor: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    guardian_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    guardian_verification_method: Mapped[str | None] = mapped_column(String(30), nullable=True)

    identity_path: Mapped[str] = mapped_column(String(50), nullable=False)
    identity_status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="verified")
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="active")
    merged_into_patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=True)

    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class PatientIdentifier(Base, UUIDPk, Timestamps):
    __tablename__ = "patient_identifiers"
    __table_args__ = (
        # Unique constraint left as-is per team decision — only check
        # constraints were in scope for the ck_<table>_<column> rename.
        UniqueConstraint("patient_id", "identifier_type", name="patient_identifier_type"),
        CheckConstraint(IdentifierType.sql_check("identifier_type"), name="identifier_type"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)
    identifier_type: Mapped[str] = mapped_column(String(50), nullable=False)
    identifier_value_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    identifier_blind_index: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    captured_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class PatientMergeLog(Base, UUIDPk, Timestamps):
    __tablename__ = "patient_merge_log"
    __table_args__ = (
        CheckConstraint(MergeSourceType.sql_check("source_type"), name="source_type"),
        CheckConstraint(MergeStatus.sql_check("status"), name="status"),
    )

    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)
    target_patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)

    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Should-fix (PR review): reject_merge previously overwrote this same
    # `reason` column with why the merge was refused, destroying why it was
    # requested in the first place. Both matter for audit — kept separate.
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    unmerge_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    before_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

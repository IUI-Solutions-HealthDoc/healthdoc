import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey,
    LargeBinary, SmallInteger, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.enums import (
    Sex, IdentityPath, IdentityStatus, PatientStatus,
    IdentifierType, MergeStatus, MergeSourceType,
)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        CheckConstraint("dob IS NOT NULL OR age_years IS NOT NULL", name="dob_or_age"),
        CheckConstraint("uhid IS NOT NULL OR thid IS NOT NULL", name="has_identifier"),
        CheckConstraint(Sex.sql_check("sex"), name="sex"),
        CheckConstraint(IdentityPath.sql_check("identity_path"), name="identity_path"),
        CheckConstraint(IdentityStatus.sql_check("identity_status"), name="identity_status"),
        CheckConstraint(PatientStatus.sql_check("status"), name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))

    uhid: Mapped[str | None] = mapped_column(String(30), nullable=True)  # unique enforced by partial index, not here
    thid: Mapped[str | None] = mapped_column(String(25), unique=True, nullable=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    sex: Mapped[str] = mapped_column(String(30), nullable=False)
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

    identity_path: Mapped[str] = mapped_column(String(50), nullable=False)
    identity_status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="verified")
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="active")
    merged_into_patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=True)

    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PatientIdentifier(Base):
    __tablename__ = "patient_identifiers"
    __table_args__ = (
        UniqueConstraint("patient_id", "identifier_type", name="uq_patient_identifier_type"),
        CheckConstraint(IdentifierType.sql_check("identifier_type"), name="ck_patient_identifiers_identifier_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)
    identifier_type: Mapped[str] = mapped_column(String(50), nullable=False)
    identifier_value_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    identifier_blind_index: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    captured_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PatientMergeLog(Base):
    __tablename__ = "patient_merge_log"
    __table_args__ = (
        CheckConstraint(MergeSourceType.sql_check("source_type"), name="ck_patient_merge_log_source_type"),
        CheckConstraint(MergeStatus.sql_check("status"), name="ck_patient_merge_log_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)
    target_patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)

    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    unmerge_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    before_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
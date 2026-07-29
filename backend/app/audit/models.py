"""ORM model for audit_logs, matching migrations/versions/0003_audit.py.

The real table (production/dev Postgres) is partitioned by RANGE and has
hash-chain + append-only triggers created via raw SQL in that migration
— this ORM model does NOT recreate the partitioning or triggers. It
exists so app.audit.service can build type-safe INSERTs, and so that
tests (which use Base.metadata.create_all against a non-partitioned
test DB with no triggers) get a plain table with matching columns.

app.audit.service computes entry_hash/prev_hash/signature in Python for
every insert. In production, the BEFORE INSERT trigger unconditionally
recomputes and overwrites entry_hash/prev_hash from live DB state (the
real source of truth for the hash chain) — so Python's values are only
authoritative in the test DB, where no trigger exists.
"""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    role: Mapped[str | None] = mapped_column(Text)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    visit_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text)

    ip_address: Mapped[str | None] = mapped_column(String(45))
    device_id: Mapped[str | None] = mapped_column(Text)

    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    signer_key_id: Mapped[str] = mapped_column(Text, nullable=False)

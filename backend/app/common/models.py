"""Shared model mixins — see docs/schema-conventions.md. Use these; never hand-roll id/timestamps."""
import uuid
from datetime import datetime

from sqlalchemy import CHAR, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, declarative_mixin, mapped_column
from app.common.db import Base


@declarative_mixin
class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )


@declarative_mixin
class Timestamps:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


@declarative_mixin
class Blame:
    """Who did it. Add wherever a person causes the row."""
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )


class IdempotencyKey(Base, UUIDPk):
    """
    Schema doc §4A.1. Write-once: created, then only ever read back
    for replay, never mutated. Deliberately does NOT use the
    Timestamps mixin -- that adds updated_at, which this table
    doesn't have (see migrations/versions/0033_idempotency_keys.py).
    """
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("key", "endpoint", name="uq_idempotency_keys_key_endpoint"),
    )

    key: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    response_status: Mapped[int | None] = mapped_column(nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

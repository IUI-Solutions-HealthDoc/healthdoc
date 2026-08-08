"""Shared model mixins — see docs/schema-conventions.md. Use these; never hand-roll id/timestamps."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declarative_mixin, mapped_column


@declarative_mixin
class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )


@declarative_mixin
class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
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


class Versioned:
    """Optimistic concurrency (schema §4A.2). row_version starts at 1 and is
    bumped by the service on every update in the same transaction. GET returns
    it as ETag; PATCH/PUT must send If-Match. Mismatch => 409 stale_write."""
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

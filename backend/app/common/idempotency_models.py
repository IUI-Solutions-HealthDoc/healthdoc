"""ORM model only -- the idempotency_keys table itself is created by
migration 0002 (owned by B1), per docs/database-schema.md §4A.1. This
file does NOT create any migration; it just lets our code read/write a
table that should already exist. If you get a "table does not exist"
error using this, confirm with B1 whether 0002 actually includes it yet.
"""
import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk


class IdempotencyKey(Base, UUIDPk, Timestamps):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        # Must match 0003a exactly. user_id is IN the key deliberately:
        # idempotency keys are client-generated, so two users can emit the same
        # one against the same endpoint. Scoping only by (key, endpoint) would
        # hand the second caller the first caller's stored response — a
        # cross-user data leak wearing a replay's clothes.
        UniqueConstraint("key", "user_id", "endpoint",
                         name="uq_idempotency_keys_key_user_endpoint"),
    )

    key: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Null until the real request finishes -- see idempotency.py.
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

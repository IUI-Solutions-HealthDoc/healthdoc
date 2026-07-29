"""
Shared building blocks for every model in the project.
"""
import uuid
from sqlalchemy import Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func


class UUIDPk:
    """Adds a UUID primary key column called `id` to any model."""
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Timestamps:
    """Adds created_at / updated_at columns, auto-filled by the database."""
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Blame:
    """Adds created_by / updated_by columns pointing at the users table."""
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
"""Outbox: durable edge->cloud sync queue (B1-W6-01).

Every mutation that must reach the cloud writes an outbox row in the SAME transaction
(transactional outbox pattern). A background worker ships rows in order; conflict
resolution on the cloud side uses the sensitivity tier (normal/important/critical —
critical never auto-resolves). See docs/database-schema.md §7.
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import UUIDPk, Timestamps


class OutboxEvent(Base, UUIDPk, Timestamps):
    __tablename__ = "outbox_events"

    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False)   # 'patient', 'invoice'...
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)       # created|updated|...
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(50), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")  # pending|sent|failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sequence: Mapped[int] = mapped_column(BigInteger, server_default=func.nextval("seq_outbox"))

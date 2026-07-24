import uuid
from datetime import datetime, date
from sqlalchemy import String, Boolean, Date, DateTime, ForeignKey, UniqueConstraint, func, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.common.db import Base
from app.common.enums import QueueTokenStatus, QueuePriority


class Queue(Base):
    __tablename__ = "queues"
    __table_args__ = (
        UniqueConstraint("department_id", "doctor_user_id", "service_date", name="uq_queue_doctor_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    doctor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    room_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rooms.id"), nullable=True)
    display_label: Mapped[str] = mapped_column(String(50), nullable=True)
    now_serving_token_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("queue_tokens.id"), nullable=True)
    service_date: Mapped[date] = mapped_column(Date(), nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    tokens: Mapped[list["QueueToken"]] = relationship(back_populates="queue", foreign_keys="QueueToken.queue_id")
    now_serving_token: Mapped["QueueToken"] = relationship("QueueToken", foreign_keys=[now_serving_token_id])



class QueueToken(Base):
    __tablename__ = "queue_tokens"
    __table_args__ = (
        UniqueConstraint("queue_id", "sequence", name="uq_queue_token_sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    queue_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("queues.id"), nullable=False)
    visit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("visits.id"), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    token_display: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="waiting")
    priority: Mapped[str] = mapped_column(String(50), nullable=False, server_default="normal")
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    queue: Mapped["Queue"] = relationship(back_populates="tokens", foreign_keys=[queue_id])

import uuid
from datetime import datetime, date
from sqlalchemy import String, Boolean, Date, DateTime, ForeignKey, UniqueConstraint, func, Integer, SmallInteger, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.common.db import Base
from app.common.models import Timestamps, UUIDPk

class Roster(Base, UUIDPk, Timestamps):
    __tablename__ = "rosters"
    __table_args__ = (
        UniqueConstraint("staff_user_id", "roster_date", "shift", name="uq_roster_staff_date_shift"),
    )
 
    staff_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    room_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("rooms.id"), nullable=True)
    shift: Mapped[str] = mapped_column(String(50), nullable=False)
    roster_date: Mapped[date] = mapped_column(Date(), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Queue(Base, UUIDPk, Timestamps):
    __tablename__ = "queues"
    __table_args__ = (
        UniqueConstraint("department_id", "doctor_user_id", "service_date", name="uq_queue_doctor_date"),
    )

    __audit_resource_type__ = "queues"
    __audit_facility_id_field__ = "facility_id"
    __audit_department_id_field__ = "department_id"

    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    doctor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    room_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("rooms.id"), nullable=True)
    display_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    now_serving_token_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("queue_tokens.id"), nullable=True)
    service_date: Mapped[date] = mapped_column(Date(), nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    tokens: Mapped[list["QueueToken"]] = relationship(back_populates="queue", foreign_keys="QueueToken.queue_id")
    now_serving_token: Mapped["QueueToken"] = relationship("QueueToken", foreign_keys=[now_serving_token_id])


class QueueCounter(Base, UUIDPk, Timestamps):
    """One row per (department, day) -- NOT per queue. Two doctors in the
    same department share a display board, so they must share a counter,
    or both could show "MED-001" on the same screen."""
    __tablename__ = "queue_counters"
    __table_args__ = (
        UniqueConstraint("department_id", "counter_date", name="uq_queue_counter_department_date"),
    )
 
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    counter_date: Mapped[date] = mapped_column(Date(), nullable=False)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    
class QueueToken(Base, UUIDPk, Timestamps):
    __tablename__ = "queue_tokens"
    __table_args__ = (
        UniqueConstraint("queue_id", "sequence", name="uq_queue_token_sequence"),
    )
    __audit_resource_type__ = "queue_tokens"
    __audit_facility_id_field__ = "facility_id"
    __audit_visit_id_field__ = "visit_id"

    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    queue_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("queues.id"), nullable=False)
    visit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("visits.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    token_display: Mapped[str] = mapped_column(String(20), nullable=False)
    initial_priority: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="waiting")
    priority: Mapped[str] = mapped_column(String(50), nullable=False, server_default="normal")
    priority_rank: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="6")
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    queue: Mapped["Queue"] = relationship(back_populates="tokens", foreign_keys=[queue_id])


class QueueTokenPriorityChange(Base, UUIDPk):
    """No Timestamps mixin here on purpose -- that mixin adds updated_at,
    and this table is never updated, only ever inserted into."""
    __tablename__ = "queue_token_priority_changes"
 
    queue_token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("queue_tokens.id"), nullable=False
    )
    from_priority: Mapped[str] = mapped_column(String(50), nullable=False)
    to_priority: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    

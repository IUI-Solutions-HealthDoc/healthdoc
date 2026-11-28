"""Housekeeping tasks: cleaning a room or bed, recorded (migration 0104).

The task that matters most is the one nobody asks for: a bed vacated by a
discharge or a transfer is dirty. Discharge and transfer now create a bed
turnover task and put the bed in 'cleaning', so admission cannot offer it
until housekeeping says it is done. Other tasks (a spill, a routine clean,
an isolation terminal clean) are raised by ward staff.

The person who cleans is often an outsourced worker with no HealthDoc login,
so who did it is the signed-in user who recorded it plus a free-text name.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk

TASK_TYPES = ("bed_turnover", "terminal_clean", "routine_clean", "spill", "linen_change", "other")
TASK_PRIORITIES = ("routine", "urgent")
TASK_STATUSES = ("pending", "in_progress", "done", "cancelled")
TASK_SOURCES = ("discharge", "transfer", "manual")
OPEN_STATUSES = ("pending", "in_progress")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class HousekeepingTask(Base, UUIDPk, Timestamps):
    __tablename__ = "housekeeping_tasks"
    __audit_resource_type__ = "housekeeping_tasks"
    __audit_facility_id_field__ = "facility_id"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    ward_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("wards.id", ondelete="RESTRICT"), nullable=False)
    bed_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("beds.id", ondelete="RESTRICT"))
    #: The stay whose end created this task, when one did.
    admission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admissions.id", ondelete="RESTRICT")
    )
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[str] = mapped_column(String(50), nullable=False, default="routine", server_default="routine")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual", server_default="manual")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", server_default="pending")
    notes: Mapped[str | None] = mapped_column(Text)
    #: NULL when the system raised it (a discharge, a transfer).
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    #: The cleaner's name as told; often an outsourced worker with no login.
    assigned_to_name: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    # What was done, ticked on completion. Booleans, not a checklist blob, so a
    # report can ask "turnovers without mattress disinfection" in plain SQL.
    linen_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    mattress_disinfected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    surfaces_disinfected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    waste_removed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    #: The laundry batch the stripped linen went into, when it was sent from here.
    linen_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("linen_batches.id", ondelete="RESTRICT")
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(f"task_type IN ({_in(TASK_TYPES)})", name="ck_housekeeping_tasks_task_type"),
        CheckConstraint(f"priority IN ({_in(TASK_PRIORITIES)})", name="ck_housekeeping_tasks_priority"),
        CheckConstraint(f"status IN ({_in(TASK_STATUSES)})", name="ck_housekeeping_tasks_status"),
        CheckConstraint(f"source IN ({_in(TASK_SOURCES)})", name="ck_housekeeping_tasks_source"),
        CheckConstraint(
            "status <> 'cancelled' OR (cancel_reason IS NOT NULL AND trim(cancel_reason) <> '')",
            name="ck_housekeeping_tasks_cancel_reason",
        ),
        CheckConstraint("status <> 'done' OR completed_at IS NOT NULL", name="ck_housekeeping_tasks_completed_at"),
        # One open turnover per bed: a second discharge cannot happen before the
        # bed is clean, and a retried discharge must not queue the bed twice.
        Index(
            "uq_housekeeping_tasks_open_bed_turnover", "bed_id", unique=True,
            sqlite_where=text("task_type = 'bed_turnover' AND status IN ('pending', 'in_progress')"),
            postgresql_where=text("task_type = 'bed_turnover' AND status IN ('pending', 'in_progress')"),
        ),
        Index("ix_housekeeping_tasks_facility_status", "facility_id", "status"),
        Index("ix_housekeeping_tasks_ward_id", "ward_id"),
        Index("ix_housekeeping_tasks_bed_id", "bed_id"),
        Index("ix_housekeeping_tasks_admission_id", "admission_id"),
        Index("ix_housekeeping_tasks_linen_batch_id", "linen_batch_id"),
        Index("ix_housekeeping_tasks_requested_by", "requested_by"),
        Index("ix_housekeeping_tasks_started_by", "started_by"),
        Index("ix_housekeeping_tasks_completed_by", "completed_by"),
    )

"""Housekeeping task rules.

A vacated bed goes to 'cleaning' with a turnover task in the same transaction
as the discharge or transfer that vacated it. Completing the task is what
returns the bed to 'vacant'. Cancelling one says why, and frees the bed too:
the person cancelling is saying it does not need cleaning, on the record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import Bed, Ward
from app.housekeeping.models import OPEN_STATUSES, HousekeepingTask
from app.laundry import service as laundry


class HousekeepingError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


async def request_bed_turnover(
    db: AsyncSession, *, bed: Bed, admission_id: uuid.UUID, source: str, priority: str = "urgent",
) -> HousekeepingTask | None:
    """Put a vacated bed into cleaning and raise its turnover task.

    Called by discharge and transfer instead of setting the bed 'vacant'. A bed
    already in maintenance stays there: it is out of service for another reason.
    """
    if bed.status == "maintenance":
        return None
    ward = await db.get(Ward, bed.ward_id)
    bed.status = "cleaning"
    open_task = (
        await db.execute(
            select(HousekeepingTask).where(
                HousekeepingTask.bed_id == bed.id, HousekeepingTask.task_type == "bed_turnover",
                HousekeepingTask.status.in_(OPEN_STATUSES),
            )
        )
    ).scalar_one_or_none()
    if open_task is not None:
        return open_task
    task = HousekeepingTask(
        id=uuid.uuid4(), facility_id=ward.facility_id, ward_id=bed.ward_id, bed_id=bed.id,
        admission_id=admission_id, task_type="bed_turnover", priority=priority, source=source,
        status="pending", requested_by=None, requested_at=datetime.now(UTC),
    )
    db.add(task)
    return task


async def get_scoped(db: AsyncSession, task_id: uuid.UUID, facility_id: uuid.UUID, *, lock: bool = False) -> HousekeepingTask:
    stmt = select(HousekeepingTask).where(HousekeepingTask.id == task_id, HousekeepingTask.facility_id == facility_id)
    if lock:
        stmt = stmt.with_for_update()
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise HousekeepingError("task_not_found", "Housekeeping task not found", 404)
    return task


async def raise_task(
    db: AsyncSession, *, facility_id: uuid.UUID, user_id: uuid.UUID, ward_id: uuid.UUID, bed_id: uuid.UUID | None,
    task_type: str, priority: str, notes: str | None,
) -> HousekeepingTask:
    ward = await db.get(Ward, ward_id)
    if ward is None or ward.facility_id != facility_id:
        raise HousekeepingError("ward_not_found", "Ward not found", 404)
    if bed_id is not None:
        bed = await db.get(Bed, bed_id)
        if bed is None or bed.ward_id != ward_id:
            raise HousekeepingError("bed_not_found", "Bed not found in that ward", 404)
    if task_type == "bed_turnover":
        # Turnovers come from discharge and transfer, which also hold the bed.
        raise HousekeepingError("turnover_is_automatic", "Bed turnovers are raised by discharge and transfer", 422)
    notes = (notes or "").strip() or None
    if task_type == "other" and notes is None:
        raise HousekeepingError("notes_required", "Say what needs doing", 422)
    task = HousekeepingTask(
        id=uuid.uuid4(), facility_id=facility_id, ward_id=ward_id, bed_id=bed_id, task_type=task_type,
        priority=priority, source="manual", status="pending", notes=notes, requested_by=user_id,
        requested_at=datetime.now(UTC),
    )
    db.add(task)
    await db.flush()
    return task


def _open(task: HousekeepingTask) -> None:
    if task.status not in OPEN_STATUSES:
        raise HousekeepingError("task_closed", f"This task is already {task.status}")


async def start(db: AsyncSession, task: HousekeepingTask, *, user_id: uuid.UUID, assigned_to_name: str | None) -> HousekeepingTask:
    _open(task)
    if task.status == "in_progress":
        raise HousekeepingError("task_started", "This task has already been started")
    task.status, task.started_at, task.started_by = "in_progress", datetime.now(UTC), user_id
    task.assigned_to_name = (assigned_to_name or "").strip() or task.assigned_to_name
    await db.flush()
    return task


async def _free_bed(db: AsyncSession, task: HousekeepingTask) -> None:
    if task.bed_id is None or task.task_type != "bed_turnover":
        return
    bed = (await db.execute(select(Bed).where(Bed.id == task.bed_id).with_for_update())).scalar_one_or_none()
    if bed is not None and bed.status == "cleaning":
        bed.status = "vacant"


async def complete(
    db: AsyncSession, task: HousekeepingTask, *, user_id: uuid.UUID, assigned_to_name: str | None,
    linen_changed: bool, mattress_disinfected: bool, surfaces_disinfected: bool, waste_removed: bool,
    notes: str | None, linen_items: list[tuple[str, int]] | None = None, linen_infected: bool = False,
) -> HousekeepingTask:
    _open(task)
    if task.task_type in ("bed_turnover", "terminal_clean") and not (
        linen_changed and mattress_disinfected and surfaces_disinfected
    ):
        # A bed is not ready for the next patient until all three are done.
        raise HousekeepingError(
            "turnover_incomplete",
            "A bed is ready only when the linen is changed and the mattress and surfaces are disinfected",
            422,
        )
    now = datetime.now(UTC)
    if linen_items:
        batch = await laundry.collect(
            db, facility_id=task.facility_id, user_id=user_id, items=linen_items, ward_id=task.ward_id,
            bed_id=task.bed_id, is_infected=linen_infected, notes="Stripped during housekeeping",
        )
        task.linen_batch_id = batch.id
    task.status, task.completed_at, task.completed_by = "done", now, user_id
    if task.started_at is None:
        task.started_at, task.started_by = now, user_id
    task.assigned_to_name = (assigned_to_name or "").strip() or task.assigned_to_name
    task.linen_changed, task.mattress_disinfected = linen_changed, mattress_disinfected
    task.surfaces_disinfected, task.waste_removed = surfaces_disinfected, waste_removed
    notes = (notes or "").strip() or None
    if notes:
        task.notes = f"{task.notes}\n{notes}" if task.notes else notes
    await _free_bed(db, task)
    await db.flush()
    return task


async def cancel(db: AsyncSession, task: HousekeepingTask, *, user_id: uuid.UUID, reason: str) -> HousekeepingTask:
    _open(task)
    reason = (reason or "").strip()
    if not reason:
        raise HousekeepingError("reason_required", "Say why the task is cancelled", 422)
    task.status, task.cancel_reason = "cancelled", reason
    task.completed_at, task.completed_by = datetime.now(UTC), user_id
    await _free_bed(db, task)
    await db.flush()
    return task

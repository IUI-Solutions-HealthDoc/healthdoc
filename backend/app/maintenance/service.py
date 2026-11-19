"""Facility-safe append and read operations for maintenance evidence."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.departments.models import Department
from app.maintenance.models import MachineMaintenanceLog
from app.maintenance.schemas import MaintenanceLogCreate


class DepartmentNotFound(Exception):
    pass


class MaintenanceLogNotFound(Exception):
    pass


class MaintenanceRefused(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message


async def _registered_machine(db: AsyncSession, facility_id: uuid.UUID, machine: str) -> str:
    """The register's name for a machine, or the typed text when none is registered.

    Service records named machines in free text while the equipment register
    held them separately, so "MR-01" had a service history and the doctor's
    Equipment page said no machines were registered (QA 17 Oct 2026). Once a
    facility registers equipment, a record must name one of its machines, by
    asset tag or name in any case, and the tag is what is stored.
    """
    from app.equipment.models import Equipment

    registered = (
        await db.execute(select(Equipment).where(Equipment.facility_id == facility_id))
    ).scalars().all()
    if not registered:
        return machine.strip().upper()
    wanted = machine.strip().upper()
    for item in registered:
        if (item.asset_tag or "").upper() == wanted or item.name.strip().upper() == wanted:
            if item.status == "retired":
                raise MaintenanceRefused("machine_retired", f"{item.name} is retired. Service is not recorded on a retired machine.")
            return (item.asset_tag or item.name).strip().upper()
    raise MaintenanceRefused(
        "machine_not_registered",
        "This machine is not in the equipment register. Choose a registered machine, or ask an administrator to register it under Equipment.",
    )


async def create_maintenance_log(
    db: AsyncSession,
    *,
    payload: MaintenanceLogCreate,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> MachineMaintenanceLog:
    department = (
        await db.execute(
            select(Department).where(
                Department.id == payload.department_id,
                Department.facility_id == facility_id,
            )
        )
    ).scalar_one_or_none()
    if department is None:
        raise DepartmentNotFound
    if not (payload.performed_by_vendor or "").strip():
        # Who did the work is the point of the record (QA 17 Oct 2026).
        raise MaintenanceRefused(
            "performed_by_required", "Enter who performed the service: the vendor, or the in-house engineer's name.",
        )
    if payload.maintenance_type == "breakdown" and payload.downtime_minutes is None:
        raise MaintenanceRefused("downtime_required", "Enter how long the machine was out of use for a breakdown.")
    machine = await _registered_machine(db, facility_id, payload.machine_id)

    row = MachineMaintenanceLog(
        id=uuid.uuid4(),
        machine_id=machine,
        department_id=department.id,
        maintenance_type=payload.maintenance_type,
        performed_at=payload.performed_at,
        performed_by_vendor=payload.performed_by_vendor,
        downtime_minutes=payload.downtime_minutes,
        notes=payload.notes,
        created_by=actor_id,
    )
    db.add(row)
    await db.flush()
    await write_audit_log(
        db,
        facility_id=facility_id,
        action="create",
        resource_type="machine_maintenance_logs",
        resource_id=row.id,
        user_id=actor_id,
        new_value={
            "machine_id": row.machine_id,
            "department_id": str(row.department_id),
            "maintenance_type": row.maintenance_type,
            "performed_at": row.performed_at.isoformat(),
            "downtime_minutes": row.downtime_minutes,
        },
    )
    await db.refresh(row)
    return row


def _scoped_logs(facility_id: uuid.UUID):
    return (
        select(MachineMaintenanceLog)
        .join(Department, Department.id == MachineMaintenanceLog.department_id)
        .where(Department.facility_id == facility_id)
    )


async def get_maintenance_log(
    db: AsyncSession, *, log_id: uuid.UUID, facility_id: uuid.UUID
) -> MachineMaintenanceLog:
    row = (
        await db.execute(
            _scoped_logs(facility_id).where(MachineMaintenanceLog.id == log_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise MaintenanceLogNotFound
    return row


async def list_maintenance_logs(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    machine_id: str | None = None,
    department_id: uuid.UUID | None = None,
    maintenance_type: str | None = None,
    performed_from: datetime | None = None,
    performed_to: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[MachineMaintenanceLog], int]:
    statement = _scoped_logs(facility_id)
    if machine_id is not None:
        # Part of a name or tag, any case: typing "mr" found nothing because
        # the filter wanted the exact stored value (QA 17 Oct 2026).
        term = machine_id.strip().replace("%", "").replace("_", "")
        statement = statement.where(MachineMaintenanceLog.machine_id.ilike(f"%{term}%"))
    if department_id is not None:
        statement = statement.where(
            MachineMaintenanceLog.department_id == department_id
        )
    if maintenance_type is not None:
        statement = statement.where(
            MachineMaintenanceLog.maintenance_type == maintenance_type
        )
    if performed_from is not None:
        statement = statement.where(
            MachineMaintenanceLog.performed_at >= performed_from
        )
    if performed_to is not None:
        statement = statement.where(MachineMaintenanceLog.performed_at <= performed_to)

    total = (
        await db.execute(select(func.count()).select_from(statement.subquery()))
    ).scalar_one()
    rows = await db.execute(
        statement.order_by(
            MachineMaintenanceLog.performed_at.desc(),
            MachineMaintenanceLog.created_at.desc(),
            MachineMaintenanceLog.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.scalars().all()), total

"""Equipment register rules.

Kept small on purpose: what matters to a hospital and to the control room is
that a status change is recorded with a reason, by a named person, and that a
retired machine stays retired.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.equipment.models import Equipment, EquipmentStatusEvent

#: Not usable now. The control room counts these as "not working".
NOT_WORKING = ("down", "maintenance")


class EquipmentError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


async def get_scoped(db: AsyncSession, equipment_id: uuid.UUID, facility_id: uuid.UUID, *, lock: bool = False) -> Equipment:
    stmt = select(Equipment).where(Equipment.id == equipment_id, Equipment.facility_id == facility_id)
    if lock:
        stmt = stmt.with_for_update()
    equipment = (await db.execute(stmt)).scalar_one_or_none()
    if equipment is None:
        # 404, never 403: another facility's machine does not exist for this caller.
        raise EquipmentError("equipment_not_found", "Equipment not found", 404)
    return equipment


async def register(
    db: AsyncSession, *, facility_id: uuid.UUID, user_id: uuid.UUID, name: str, category: str,
    location: str | None, asset_tag: str | None, is_critical: bool,
) -> Equipment:
    tag = asset_tag.strip() if asset_tag and asset_tag.strip() else None
    if tag is not None:
        clash = await db.execute(
            select(Equipment.id).where(Equipment.facility_id == facility_id, Equipment.asset_tag == tag)
        )
        if clash.first() is not None:
            raise EquipmentError("asset_tag_in_use", f"Asset tag {tag} is already registered here")
    now = datetime.now(UTC)
    equipment = Equipment(
        id=uuid.uuid4(), facility_id=facility_id, name=name.strip(), category=category,
        location=(location or "").strip() or None, asset_tag=tag, is_critical=is_critical,
        status="working", status_since=now, created_by=user_id,
    )
    db.add(equipment)
    db.add(EquipmentStatusEvent(
        id=uuid.uuid4(), equipment_id=equipment.id, facility_id=facility_id, from_status=None,
        to_status="working", reason="registered", changed_by=user_id, changed_at=now,
    ))
    await db.flush()
    return equipment


async def change_status(
    db: AsyncSession, equipment: Equipment, *, to_status: str, reason: str | None, user_id: uuid.UUID,
) -> Equipment:
    reason = (reason or "").strip() or None
    if equipment.status == "retired":
        raise EquipmentError("equipment_retired", "A retired machine cannot change status")
    if to_status == equipment.status:
        raise EquipmentError("status_unchanged", f"Already {to_status}")
    if to_status != "working" and reason is None:
        # The reason is what the engineer and the control room act on.
        raise EquipmentError("reason_required", "Say what is wrong or why", 422)
    now = datetime.now(UTC)
    db.add(EquipmentStatusEvent(
        id=uuid.uuid4(), equipment_id=equipment.id, facility_id=equipment.facility_id,
        from_status=equipment.status, to_status=to_status, reason=reason, changed_by=user_id, changed_at=now,
    ))
    equipment.status, equipment.status_since, equipment.status_reason = to_status, now, reason
    await db.flush()
    return equipment

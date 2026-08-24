"""ORM model and admin endpoints for facility_modules (migration 0027).

`facility_modules` decides whether pharmacy, lab, radiology, OT and blood bank
work at all for a hospital — `require_module()` gates every endpoint in those
five modules on it. Before this there was:

  * no ORM model (one of the tables that exist in migrations and nowhere else),
  * no way to read the rows: GET /facility/capabilities returns only
    {code: bool} and fabricates `config` as empty dicts,
  * **no way to write them.** Enabling or disabling a module for a facility —
    a day-one provisioning action — was possible only by direct SQL against
    production.

DEFAULT-ON IS THE EXISTING RULE, AND IT IS PRESERVED.
app/common/modules.py: "No facility_modules row => module ENABLED (default-on)."
So a facility with no rows has everything on, and the toggle below upserts
rather than assuming a row exists. Changing that default would silently disable
every optional module for every existing facility, which is why the write path
is an upsert and not an update.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.deps import CurrentDbUser, require_roles
from app.common.cache import invalidate
from app.common.db import Base, get_db
from app.common.enums import ModuleCode
from app.common.models import Timestamps, UUIDPk


class FacilityModule(Base, UUIDPk, Timestamps):
    """The row 0027 created and nothing mapped.

    Written as a model rather than more raw SQL because the write path needs
    the CHECK constraint's module_code vocabulary and the unique
    (facility_id, module_code) key to be visible to the code that upserts on
    them — and because `config`, `enabled_at`, `disabled_at` and
    `disabled_reason` are columns no code has ever read.
    """

    __tablename__ = "facility_modules"
    __table_args__ = (
        CheckConstraint(ModuleCode.sql_check("module_code"), name="module_code"),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False
    )
    module_code: Mapped[str] = mapped_column(String(50), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'{}'::jsonb")
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_reason: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- schemas


class FacilityModuleOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID | None = None
    facility_id: uuid.UUID
    module_code: str
    is_enabled: bool
    config: dict = Field(default_factory=dict)
    enabled_at: datetime | None = None
    disabled_at: datetime | None = None
    disabled_reason: str | None = None


class FacilityModuleListOut(BaseModel):
    items: list[FacilityModuleOut]


class FacilityModuleUpdate(BaseModel):
    is_enabled: bool
    disabled_reason: str | None = Field(
        default=None,
        description="Required when disabling. A module switched off with no "
                    "reason is indistinguishable from one switched off by "
                    "accident, and the effect is that a whole department's "
                    "endpoints start returning 409.",
    )
    config: dict | None = None


# ---------------------------------------------------------------- router

router = APIRouter(prefix="/facility/modules", tags=["facility"])

_ADMIN = (Depends(require_roles("admin")),)
_DB_DEPENDENCY = Depends(get_db)


@router.get("", response_model=FacilityModuleListOut, dependencies=list(_ADMIN))
async def list_facility_modules(
    current_db_user: CurrentDbUser,
    db: AsyncSession = _DB_DEPENDENCY,
) -> FacilityModuleListOut:
    """Every toggleable module with its state at the caller's facility.

    Returns a row for all five module codes even where the table has none,
    because absence means ENABLED (see module docstring) and an admin screen
    that showed only stored rows would display an empty list for a brand-new
    facility that in fact has everything switched on. The synthesised rows
    carry `id=None`, which is how a caller can tell a default from a decision.
    """
    stored = {
        row.module_code: row
        for row in (
            await db.execute(
                select(FacilityModule).where(
                    FacilityModule.facility_id == current_db_user.facility_id
                )
            )
        ).scalars()
    }

    items: list[FacilityModuleOut] = []
    for code in ModuleCode.values():
        row = stored.get(code)
        if row is not None:
            items.append(FacilityModuleOut.model_validate(row))
        else:
            items.append(
                FacilityModuleOut(
                    facility_id=current_db_user.facility_id,
                    module_code=code,
                    is_enabled=True,
                )
            )
    return FacilityModuleListOut(items=items)


@router.patch(
    "/{module_code}", response_model=FacilityModuleOut, dependencies=list(_ADMIN)
)
async def update_facility_module(
    module_code: str,
    payload: FacilityModuleUpdate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = _DB_DEPENDENCY,
) -> FacilityModuleOut:
    """Enable or disable one module at the caller's own facility.

    Upsert, not update: a facility with no row has the module enabled by
    default, so the first time anybody disables one there is nothing to update.

    `disabled_reason` is required when disabling. Turning a module off makes
    every endpoint in it answer 409 for the whole hospital, and the next
    administrator to look needs to know whether that was deliberate.
    """
    if module_code not in ModuleCode.values():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "not_a_toggleable_module",
                "message": (
                    f"'{module_code}' is not toggleable. Only "
                    f"{sorted(ModuleCode.values())} can be switched off; "
                    "everything else is core."
                ),
            },
        )

    if not payload.is_enabled and not (payload.disabled_reason or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "disabled_reason_required",
                "message": "A reason is required when disabling a module.",
            },
        )

    row = (
        await db.execute(
            select(FacilityModule).where(
                FacilityModule.facility_id == current_db_user.facility_id,
                FacilityModule.module_code == module_code,
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    if row is None:
        row = FacilityModule(
            id=uuid.uuid4(),
            facility_id=current_db_user.facility_id,
            module_code=module_code,
            is_enabled=payload.is_enabled,
            config=payload.config or {},
        )
        db.add(row)
    else:
        row.is_enabled = payload.is_enabled
        if payload.config is not None:
            row.config = payload.config

    # enabled_at / disabled_at record WHEN the state last changed, which is the
    # question asked during an incident review. Only the relevant one moves.
    if payload.is_enabled:
        row.enabled_at = now
        row.disabled_reason = None
    else:
        row.disabled_at = now
        row.disabled_reason = payload.disabled_reason

    await db.flush()
    await db.commit()
    await db.refresh(row)
    await invalidate("facility-capabilities", str(current_db_user.facility_id))
    return FacilityModuleOut.model_validate(row)

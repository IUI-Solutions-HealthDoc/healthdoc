"""Which facilities of this deployment speak to ABDM, and as whom.

One bridge carries several services, and every M2/M3 call says which one is
speaking (X-HIP-ID, X-HIU-ID). A facility's identity comes from operations,
never from a default:

  first facility   facilities.hfr_facility_id = ABDM_HFR_FACILITY_ID; it speaks
                   as ABDM_HIP_ID and ABDM_HIU_ID (one value for all three in
                   the sandbox, IN0910034387, 5 Oct 2026)
  each additional  an HFR id in ABDM_ADDITIONAL_HFR_FACILITY_IDS; NHA addresses
                   a facility linked to the bridge by that id, so it is its HIP
                   id and its HIU id

An HFR id on a facility row is not enough on its own: the facility must also be
linked to this bridge at NHA, which only operations know. Accepting a callback
addressed to an id we do not serve would attribute another organisation's
traffic to one of ours, so an unknown id is refused.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.config import get_settings
from app.users.models import Facility

_PLACEHOLDER = "change-me"
Role = Literal["hip", "hiu"]


class FacilityNotServed(ValueError):
    """The facility is not one of this bridge's ABDM services."""


def _set(value: str | None) -> str | None:
    value = (value or "").strip()
    return value if value and value != _PLACEHOLDER else None


def _services(role: Role) -> dict[str, str]:
    """Service id -> HFR facility id, for one role."""
    settings = get_settings()
    services: dict[str, str] = {}
    primary_hfr = _set(settings.abdm_hfr_facility_id)
    primary = _set(settings.abdm_hip_id if role == "hip" else settings.abdm_hiu_id)
    if primary:
        # With no HFR id it is still ours to answer for, but routes to no facility.
        services[primary] = primary_hfr or ""
    for raw in (settings.abdm_additional_hfr_facility_ids or "").split(","):
        hfr = _set(raw)
        if hfr and hfr != primary_hfr:
            if services.get(hfr, hfr) != hfr:
                raise FacilityNotServed(f"{hfr} is already another facility's {role.upper()} id")
            services[hfr] = hfr
    return services


def served_ids(role: Role) -> frozenset[str]:
    """Every id this bridge answers to in one role."""
    return frozenset(_services(role))


def require_served(role: Role, service_id: str | None) -> str:
    """The service id itself, once this bridge serves it in that role."""
    if not service_id or service_id not in _services(role):
        raise FacilityNotServed("This facility is not an ABDM service of this bridge")
    return service_id


async def service_id_for(db: AsyncSession, facility_id: uuid.UUID, role: Role) -> str:
    """The identity a facility's calls go out under, in one role."""
    facility = await db.get(Facility, facility_id)
    if facility is not None and facility.is_active and facility.hfr_facility_id:
        for service_id, hfr in _services(role).items():
            if hfr == facility.hfr_facility_id:
                return service_id
    raise FacilityNotServed("This facility is not an ABDM service of this bridge")


async def facility_for_service_id(
    db: AsyncSession, service_id: str | None, role: Role
) -> Facility | None:
    """The facility an inbound callback addressed, if this bridge serves it."""
    hfr = _services(role).get(service_id or "")
    if not hfr:
        return None
    return (
        await db.execute(
            select(Facility).where(Facility.hfr_facility_id == hfr, Facility.is_active.is_(True))
        )
    ).scalar_one_or_none()


def served_hfr_ids() -> frozenset[str]:
    """The HFR facility ids of every facility this bridge serves."""
    return (frozenset(_services("hip").values()) | frozenset(_services("hiu").values())) - {""}

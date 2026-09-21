"""ABDM M1 Scan-and-Share reception tickets; check-in does not create an OPD visit."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.patient_scope import require_patient_access
from app.integrations.abdm.models import ScanShareTicket
from app.patients.models import Patient


async def _staff_only(current_user: CurrentDbUser) -> None:
    # Unbound profile tickets can contain PII too. A mixed patient/staff token
    # must not bypass patient binding by selecting one of those tickets.
    if "patient" in current_user.roles:
        raise HTTPException(403, "A staff-only reception session is required")


router = APIRouter(
    prefix="/abdm/scan-share",
    tags=["abdm-scan-share"],
    dependencies=[Depends(require_roles("receptionist", "admin", "registration")), Depends(_staff_only)],
)
DbSession = Annotated[AsyncSession, Depends(get_db)]


class ScanShareTicketItem(BaseModel):
    id: uuid.UUID
    token_number: str
    abha_address: str
    status: str
    counter: str | None = None
    patient_id: uuid.UUID | None = None
    patient_uhid: str | None = None
    patient_name: str | None = None
    mobile: str | None = None
    abha_number: str | None = None
    profile_data: dict[str, Any]
    expires_at: datetime
    created_at: datetime
    checked_in_at: datetime | None = None


class ScanShareCheckInPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counter: str = Field(min_length=1, max_length=50, description="Actual reception counter label")

    @field_validator("counter")
    @classmethod
    def valid_counter(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Enter a valid reception counter")
        return value


class ScanShareCheckInResponse(BaseModel):
    ticket_id: uuid.UUID
    token_number: str
    counter: str
    patient_id: uuid.UUID | None
    patient_uhid: str | None
    patient_name: str | None
    abha_address: str
    check_in_time: datetime | None
    slip_barcode_data: str


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _status(ticket: ScanShareTicket) -> str:
    if ticket.status == "active" and _utc(ticket.expires_at) <= datetime.now(UTC):
        return "expired"
    return ticket.status


def _item(ticket: ScanShareTicket, patient: Patient | None) -> ScanShareTicketItem:
    return ScanShareTicketItem(
        id=ticket.id, token_number=ticket.token_number, abha_address=ticket.abha_address,
        status=_status(ticket), counter=ticket.counter, patient_id=ticket.patient_id,
        patient_uhid=patient.uhid if patient else None,
        patient_name=patient.full_name if patient else None,
        mobile=patient.mobile if patient else None,
        abha_number=patient.abha_number if patient else None,
        profile_data=ticket.profile_data or {}, expires_at=_utc(ticket.expires_at),
        created_at=_utc(ticket.created_at),
        checked_in_at=_utc(ticket.checked_in_at) if ticket.checked_in_at else None,
    )


async def _resolve_ticket(db, current_user, reference: str, *, lock: bool = False):
    """UUID identifies one ticket; a reused human token must never pick a patient."""
    try:
        ticket_id = uuid.UUID(reference)
    except ValueError:
        criterion = ScanShareTicket.token_number == reference
    else:
        criterion = ScanShareTicket.id == ticket_id
    stmt = select(ScanShareTicket).where(
        ScanShareTicket.facility_id == current_user.facility_id, criterion,
    ).limit(2)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    tickets = (await db.execute(stmt)).scalars().all()
    if not tickets:
        raise HTTPException(404, {"code": "ticket_not_found", "message": "Reception ticket not found"})
    if len(tickets) != 1:
        raise HTTPException(409, {
            "code": "ticket_ambiguous",
            "message": "This token has multiple tickets. Select the correct patient from the queue.",
        })
    ticket = tickets[0]
    patient = (
        await require_patient_access(db, ticket.patient_id, current_user)
        if ticket.patient_id else None
    )
    return ticket, patient


@router.get("/tickets", response_model=list[ScanShareTicketItem])
async def list_scan_share_tickets(
    current_user: CurrentDbUser,
    db: DbSession,
    status: Annotated[Literal["active", "checked_in", "expired", "all"], Query()] = "active",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ScanShareTicketItem]:
    now = datetime.now(UTC)
    stmt = (
        select(ScanShareTicket, Patient)
        .outerjoin(Patient, and_(
            Patient.id == ScanShareTicket.patient_id,
            Patient.facility_id == current_user.facility_id,
            Patient.deleted_at.is_(None),
        ))
        .where(
            ScanShareTicket.facility_id == current_user.facility_id,
            or_(ScanShareTicket.patient_id.is_(None), Patient.id.is_not(None)),
        )
    )
    if status == "active":
        stmt = stmt.where(ScanShareTicket.status == "active", ScanShareTicket.expires_at > now)
    elif status == "expired":
        stmt = stmt.where(or_(
            ScanShareTicket.status == "expired",
            and_(ScanShareTicket.status == "active", ScanShareTicket.expires_at <= now),
        ))
    elif status != "all":
        stmt = stmt.where(ScanShareTicket.status == status)
    rows = (await db.execute(stmt.order_by(ScanShareTicket.created_at.desc()).limit(limit))).all()
    # Enforce patient-role self binding even for accidental mixed staff roles.
    for ticket, patient in rows:
        if patient is not None:
            await require_patient_access(db, patient.id, current_user)
    return [_item(ticket, patient) for ticket, patient in rows]


@router.get("/tickets/{token_number}", response_model=ScanShareTicketItem)
async def get_scan_share_ticket(
    token_number: str, current_user: CurrentDbUser, db: DbSession,
) -> ScanShareTicketItem:
    ticket, patient = await _resolve_ticket(db, current_user, token_number)
    return _item(ticket, patient)


@router.post("/tickets/{token_number}/check-in", response_model=ScanShareCheckInResponse)
async def check_in_scan_share_ticket(
    token_number: str, payload: ScanShareCheckInPayload,
    current_user: CurrentDbUser, db: DbSession,
) -> ScanShareCheckInResponse:
    # Ticket identity + row lock is the natural idempotency key. A retry cannot
    # move counters, refresh the timestamp, create a visit or charge another fee.
    ticket, patient = await _resolve_ticket(db, current_user, token_number, lock=True)
    if ticket.status == "checked_in":
        if ticket.counter != payload.counter:
            raise HTTPException(409, {
                "code": "ticket_already_checked_in", "message": "Ticket already checked in at another counter",
            })
    elif _status(ticket) == "expired":
        raise HTTPException(409, {"code": "ticket_expired", "message": "Reception ticket has expired"})
    elif ticket.status != "active":
        raise HTTPException(409, {"code": "ticket_not_active", "message": "Reception ticket is not active"})
    else:
        ticket.status = "checked_in"
        ticket.counter = payload.counter
        ticket.checked_in_at = datetime.now(UTC)
        await db.flush()
    return ScanShareCheckInResponse(
        ticket_id=ticket.id, token_number=ticket.token_number, counter=ticket.counter,
        patient_id=ticket.patient_id, patient_uhid=patient.uhid if patient else None,
        patient_name=patient.full_name if patient else None, abha_address=ticket.abha_address,
        check_in_time=_utc(ticket.checked_in_at) if ticket.checked_in_at else None,
        # Opaque local reference only: never put ABHA, demographics or contact data in a barcode.
        slip_barcode_data=str(ticket.id),
    )

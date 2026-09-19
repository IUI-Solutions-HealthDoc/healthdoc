"""ABDM M1 Scan-and-Share counter check-in endpoints for reception desk."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.integrations.abdm.models import ScanShareTicket
from app.patients.models import Patient

router = APIRouter(
    prefix="/abdm/scan-share",
    tags=["abdm-scan-share"],
    dependencies=[Depends(require_roles("receptionist", "admin", "registration"))],
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


class ScanShareCheckInPayload(BaseModel):
    counter: str = Field(default="Counter 1", description="Assigned reception/consultation counter")
    department_id: uuid.UUID | None = Field(default=None, description="Department for consultation")


class ScanShareCheckInResponse(BaseModel):
    ticket_id: uuid.UUID
    token_number: str
    counter: str
    patient_id: uuid.UUID | None
    patient_uhid: str | None
    patient_name: str | None
    abha_address: str
    check_in_time: datetime
    slip_barcode_data: str


@router.get("/tickets", response_model=list[ScanShareTicketItem])
async def list_scan_share_tickets(
    current_user: CurrentDbUser,
    db: DbSession,
    status: Annotated[str, Query(description="Filter by ticket status: active, checked_in, expired, all")] = "active",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ScanShareTicketItem]:
    """List scan-and-share queue tickets for the receptionist desk."""
    stmt = (
        select(ScanShareTicket, Patient.uhid, Patient.full_name, Patient.mobile, Patient.abha_number)
        .outerjoin(Patient, Patient.id == ScanShareTicket.patient_id)
        .where(ScanShareTicket.facility_id == current_user.facility_id)
    )
    if status != "all":
        stmt = stmt.where(ScanShareTicket.status == status)

    stmt = stmt.order_by(ScanShareTicket.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).all()

    return [
        ScanShareTicketItem(
            id=ticket.id,
            token_number=ticket.token_number,
            abha_address=ticket.abha_address,
            status=ticket.status,
            counter=ticket.counter,
            patient_id=ticket.patient_id,
            patient_uhid=uhid,
            patient_name=full_name,
            mobile=mobile,
            abha_number=abha_num,
            profile_data=ticket.profile_data or {},
            expires_at=ticket.expires_at,
            created_at=ticket.created_at,
        )
        for ticket, uhid, full_name, mobile, abha_num in rows
    ]


@router.get("/tickets/{token_number}", response_model=ScanShareTicketItem)
async def get_scan_share_ticket(
    token_number: str,
    current_user: CurrentDbUser,
    db: DbSession,
) -> ScanShareTicketItem:
    """Look up a scan-and-share ticket by token number or scanned barcode."""
    stmt = (
        select(ScanShareTicket, Patient.uhid, Patient.full_name, Patient.mobile, Patient.abha_number)
        .outerjoin(Patient, Patient.id == ScanShareTicket.patient_id)
        .where(
            ScanShareTicket.facility_id == current_user.facility_id,
            ScanShareTicket.token_number == token_number,
        )
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ticket_not_found", "message": f"Scan-and-share ticket '{token_number}' not found"},
        )

    ticket, uhid, full_name, mobile, abha_num = row
    return ScanShareTicketItem(
        id=ticket.id,
        token_number=ticket.token_number,
        abha_address=ticket.abha_address,
        status=ticket.status,
        counter=ticket.counter,
        patient_id=ticket.patient_id,
        patient_uhid=uhid,
        patient_name=full_name,
        mobile=mobile,
        abha_number=abha_num,
        profile_data=ticket.profile_data or {},
        expires_at=ticket.expires_at,
        created_at=ticket.created_at,
    )


@router.post("/tickets/{token_number}/check-in", response_model=ScanShareCheckInResponse)
async def check_in_scan_share_ticket(
    token_number: str,
    payload: ScanShareCheckInPayload,
    current_user: CurrentDbUser,
    db: DbSession,
) -> ScanShareCheckInResponse:
    """Check in patient at reception desk and generate physical/thermal reception ticket slip."""
    stmt = (
        select(ScanShareTicket, Patient.uhid, Patient.full_name)
        .outerjoin(Patient, Patient.id == ScanShareTicket.patient_id)
        .where(
            ScanShareTicket.facility_id == current_user.facility_id,
            ScanShareTicket.token_number == token_number,
        )
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ticket_not_found", "message": f"Scan-and-share ticket '{token_number}' not found"},
        )

    ticket, uhid, full_name = row
    ticket.status = "checked_in"
    ticket.counter = payload.counter
    await db.flush()

    check_in_time = datetime.now(UTC)
    barcode_data = f"{uhid or 'TEMP'}|{ticket.token_number}|{payload.counter}|{ticket.abha_address}"

    return ScanShareCheckInResponse(
        ticket_id=ticket.id,
        token_number=ticket.token_number,
        counter=ticket.counter,
        patient_id=ticket.patient_id,
        patient_uhid=uhid,
        patient_name=full_name,
        abha_address=ticket.abha_address,
        check_in_time=check_in_time,
        slip_barcode_data=barcode_data,
    )

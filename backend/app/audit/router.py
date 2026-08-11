"""
audit module router.

Repo path: backend/app/audit/router.py

B7-W4-01: Audit query API (filters, read-only, CSV export). Spec is
docs/database-schema.md §4.4: `/audit/logs` GET (auditor, admin) —
items[]: {id, user_id, role, action, resource_type, resource_id,
patient_id, old_value, new_value, created_at, entry_hash} — filters:
user_id, patient_id, resource_type, date range. Only those roles and
only those filters — anything else (an `action` filter, cross-facility
visibility) is a product decision for Tech Lead, not something to add
silently.

Both new endpoints take `user: CurrentDbUser` and scope every query to
`user.facility_id` — never a facility_id from the request. Trusting a
client-supplied facility_id was flagged repeatedly across other PRs in
this repo (four billing-adjacent PRs got this wrong); resolving it from
the token server-side is the fix, and it's the same pattern
app/billing/service.py's facility_id_for_user() and app/departments'
role-gating already use.

Export is a separate, explicit endpoint rather than a `?format=csv` on
`/logs`, per §4.3: "large exports are explicit, audited endpoints" — the
paginated list caps at page_size<=100, the export deliberately doesn't.
Requesting an export is itself an auditable event (app/audit/actions.py:
EXPORT is listed under "Data export/print", compliance list 26.1), so
the endpoint writes one audit_logs row via write_audit_log() before it
starts streaming the CSV — see service.py's module docstring for why
that write uses the request's normal session while the CSV body itself
does not.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service
from app.audit.actions import AuditAction
from app.audit.deps import _extract_ip, select_acting_role
from app.audit.schemas import AuditLogListOut, AuditLogOut
from app.audit.service import write_audit_log
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/ping")
async def ping() -> dict:
    return {"module": "audit", "status": "stub"}


@router.get("/logs", dependencies=[Depends(require_roles("auditor", "admin"))])
async def list_audit_logs(
    user: CurrentDbUser,
    user_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
) -> dict:
    items, total = await service.list_audit_logs(
        db,
        facility_id=user.facility_id,
        user_id=user_id,
        patient_id=patient_id,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return AuditLogListOut(
        items=[AuditLogOut.model_validate(r) for r in items],
        page=page,
        page_size=page_size,
        total=total,
    ).model_dump(mode="json")


@router.get("/logs/export", dependencies=[Depends(require_roles("auditor", "admin"))])
async def export_audit_logs_csv(
    request: Request,
    user: CurrentDbUser,
    user_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    filter_bits = [
        f"{name}={value}"
        for name, value in (
            ("user_id", user_id), ("patient_id", patient_id),
            ("resource_type", resource_type),
            ("date_from", date_from), ("date_to", date_to),
        )
        if value is not None
    ]
    total = await service.count_audit_logs(
        db,
        facility_id=user.facility_id,
        user_id=user_id,
        patient_id=patient_id,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
    )

    # Recorded via the request's own session/commit cycle — this is the
    # one write this "read-only" endpoint makes, and it's the point: the
    # export itself is the compliance event, not the rows it contains.
    await write_audit_log(
        db,
        facility_id=user.facility_id,
        action=AuditAction.EXPORT,
        resource_type="audit_logs",
        user_id=user.id,
        role=select_acting_role(user.roles),
        ip_address=_extract_ip(request),
        device_id=request.headers.get("x-device-id"),
        reason=(
            f"CSV export of audit_logs, {total} row(s); "
            f"filters: {', '.join(filter_bits) or '(none)'}"
        ),
    )

    filename = f"audit_logs_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    return StreamingResponse(
        service.stream_audit_logs_csv(
            facility_id=user.facility_id,
            user_id=user_id,
            patient_id=patient_id,
            resource_type=resource_type,
            date_from=date_from,
            date_to=date_to,
        ),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

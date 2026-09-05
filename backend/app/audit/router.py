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

from app.audit import events, service
from app.audit.actions import AuditAction
from app.audit.deps import _extract_ip, select_acting_role
from app.audit.schemas import AuditLogListOut, AuditLogOut
from app.audit.service import write_audit_log
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db

router = APIRouter(prefix="/audit", tags=["audit"])


# Module-liveness stub. Gated on `admin` for the same reason ot/, outbox/,
# blood_bank/, registration/ and security_audit/ already are: an
# unauthenticated endpoint on a health system is a finding regardless of
# payload, and the response still discloses which modules exist — useful
# reconnaissance, useless to a legitimate caller.
#
# Fourteen of these were still public after the WASA M4 pass closed five of
# them, so `make contract`-style module enumeration remained available to
# anyone who could reach the host. Nothing consumes them: no frontend call, no
# e2e script, no compose healthcheck (those probe Mongo and Redis directly),
# no Grafana panel.
@router.get("/ping", dependencies=[Depends(require_roles("admin"))])
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


@router.post("/session/login", status_code=202)
async def record_login(
    request: Request,
    user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record that this user's session started.

    WHY THIS ENDPOINT EXISTS AT ALL. Authentication happens in Keycloak, not
    here — this backend only ever sees a bearer token on an already-established
    session, so there is no natural point at which it can observe a login. That
    is why events.log_login() was written and never called: there was nowhere
    to call it from.

    The honest options were a Keycloak event listener or a client that says
    "I have just signed in". This is the second. It is attributable — the row
    is written from the token's own identity, never from the body — and its
    weakness is stated rather than hidden: a client that never calls it simply
    produces no login row. It cannot be forged into someone else's name, which
    is the property that matters for an audit trail.

    Deliberately NOT role-gated beyond authentication: every role logs in, and
    a login that goes unrecorded because the role list was not updated is the
    failure this is meant to end.
    """
    await events.log_login(
        db,
        facility_id=user.facility_id,
        user_id=user.id,
        ip_address=request.client.host if request.client else None,
    )
    return {"recorded": "login"}


@router.post("/session/logout", status_code=202)
async def record_logout(
    request: Request,
    user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record that this user signed out. Same reasoning as the login route."""
    await events.log_logout(
        db,
        facility_id=user.facility_id,
        user_id=user.id,
        ip_address=request.client.host if request.client else None,
    )
    return {"recorded": "logout"}


@router.get("/resource-types", dependencies=[Depends(require_roles("auditor", "admin"))])
async def list_audit_resource_types(
    user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The resource types this facility actually has audit rows for.

    The screen's Resource dropdown was a hand-kept list of six. The table holds
    far more than that, and three of the six matched nothing — so the filter
    simultaneously offered dead options and hid most of the data. A
    hand-maintained list cannot track a vocabulary that grows every time a
    model opts into auditing.

    Facility-scoped like every other audit read: the set of resource types a
    facility holds is itself information about that facility.
    """
    values = await service.list_audit_resource_types(db, facility_id=user.facility_id)
    return {"items": values}


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

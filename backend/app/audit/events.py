"""
Manual audit events -- for the parts of compliance list 26.1 that are
NOT database row changes, so listeners.py structurally cannot see them.

Repo path: backend/app/audit/events.py

Each function here is a thin, easy-to-call wrapper around
service.write_audit_log() with the right AuditAction already filled in
-- so whoever writes the login endpoint, the export button, the
break-glass access check, etc. just calls one of these instead of
having to remember the exact field names and action spelling every
time.

WHERE TO CALL EACH ONE (since none of these fire on their own):

  log_login()   -- inside your login endpoint/flow, right after Keycloak
                   confirms the credentials are valid
  log_logout()  -- inside your logout endpoint, when the session/token
                   is invalidated
  log_view()    -- inside any endpoint that returns patient data to a
                   screen (GET /patients/{id}, /patients/{id}/history,
                   etc.) -- this is a READ, so it has to be called
                   explicitly right where the read happens
  log_role_change() -- inside whatever code calls out to Keycloak to
                   change a user's realm roles (role changes happen in
                   Keycloak, not as a row in `users` -- see schema doc)
  log_export_or_print() -- inside any "Export" / "Print" button handler
  log_break_glass_access() -- inside the code path that grants emergency
                   access to a patient's record without normal consent
                   checks (schema doc's data_access_log.emergency_access
                   flag is the DB-level marker for this same event)

Every function here still requires the SAME session as whatever else is
happening in that request, for the same reason as write_audit_log()
itself: same session = same transaction = rolls back together if
anything fails.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.audit.models import AuditLog
from app.audit.service import write_audit_log


async def log_login(
    session: AsyncSession,
    *,
    facility_id: uuid.UUID,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    device_id: str | None = None,
) -> AuditLog:
    return await write_audit_log(
        session,
        facility_id=facility_id,
        action=AuditAction.LOGIN,
        resource_type="auth",
        user_id=user_id,
        ip_address=ip_address,
        device_id=device_id,
    )


async def log_logout(
    session: AsyncSession,
    *,
    facility_id: uuid.UUID,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    device_id: str | None = None,
) -> AuditLog:
    return await write_audit_log(
        session,
        facility_id=facility_id,
        action=AuditAction.LOGOUT,
        resource_type="auth",
        user_id=user_id,
        ip_address=ip_address,
        device_id=device_id,
    )


async def log_view(
    session: AsyncSession,
    *,
    facility_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> AuditLog:
    """
    Call this from a READ endpoint (e.g. GET /patients/{id}) -- viewing
    a record is a compliance-relevant event on its own, separate from
    ever changing it. This is deliberately cheap to call so it's
    realistic to add to every patient-data read endpoint, not just the
    "important" ones.
    """
    return await write_audit_log(
        session,
        facility_id=facility_id,
        action=AuditAction.VIEW,
        resource_type=resource_type,
        resource_id=resource_id,
        patient_id=patient_id,
        reason=reason,
    )


async def log_role_change(
    session: AsyncSession,
    *,
    facility_id: uuid.UUID,
    target_user_id: uuid.UUID,
    old_roles: list[str],
    new_roles: list[str],
    changed_by_user_id: uuid.UUID | None = None,
) -> AuditLog:
    """
    Call this from whatever code actually talks to Keycloak to change a
    user's realm roles -- there is no `users.role` column to watch (role
    lives in Keycloak per the schema doc), so nothing automatic can ever
    catch this. changed_by_user_id defaults to the current request's
    actor if not given (see app/audit/context.py).
    """
    return await write_audit_log(
        session,
        facility_id=facility_id,
        action=AuditAction.ROLE_CHANGE,
        resource_type="users",
        resource_id=target_user_id,
        user_id=changed_by_user_id,
        old_value={"roles": old_roles},
        new_value={"roles": new_roles},
    )


async def log_export_or_print(
    session: AsyncSession,
    *,
    facility_id: uuid.UUID,
    action: str,  # AuditAction.EXPORT or AuditAction.PRINT
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> AuditLog:
    if action not in (AuditAction.EXPORT, AuditAction.PRINT):
        raise ValueError("action must be AuditAction.EXPORT or AuditAction.PRINT")
    return await write_audit_log(
        session,
        facility_id=facility_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        patient_id=patient_id,
        reason=reason,
    )


async def log_break_glass_access(
    session: AsyncSession,
    *,
    facility_id: uuid.UUID,
    patient_id: uuid.UUID,
    reason: str,
) -> AuditLog:
    """
    reason is required (not optional) here on purpose -- emergency
    access bypassing normal consent checks should never be silent about
    why. Pair this with a real row in data_access_log
    (emergency_access=true, migration 0004) if/when that module exposes
    a write helper of its own -- this only covers the audit_logs side.
    """
    return await write_audit_log(
        session,
        facility_id=facility_id,
        action=AuditAction.BREAK_GLASS_ACCESS,
        resource_type="patients",
        resource_id=patient_id,
        patient_id=patient_id,
        reason=reason,
    )

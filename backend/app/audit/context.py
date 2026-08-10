"""
Per-request context for the audit module.

Repo path: backend/app/audit/context.py

Populated once per request (by app/audit/deps.py's get_current_actor_dependency)
and read by write_audit_log() (app/audit/service.py) so callers don't
have to thread user_id/ip_address/device_id through every service
function by hand.

Uses contextvars, not a plain global dict — this is what makes it safe
under FastAPI's concurrent request handling. Each request gets its own
isolated values even though they all run in the same process.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AuditActor:
    """Snapshot of "who is doing this" for one request."""

    user_id: UUID | None
    role: str | None
    ip_address: str | None
    device_id: str | None


_actor_var: contextvars.ContextVar[AuditActor | None] = contextvars.ContextVar(
    "audit_actor", default=None
)


def set_current_actor(actor: AuditActor) -> None:
    _actor_var.set(actor)


def get_current_actor() -> AuditActor | None:
    """
    Returns None if nothing has set the context yet — this happens for
    background jobs, scripts, and any code path outside a normal HTTP
    request. write_audit_log() handles that case (logs a warning, writes
    NULL user_id/ip_address/device_id) rather than crashing, since those
    columns are nullable on audit_logs.

    Tech Lead answered the open question from the last review: a NULL
    actor is NOT acceptable long-term — a NULL is indistinguishable from
    a bug, so system-initiated mutations should attribute to a dedicated
    "system" user row per facility instead. Not implemented here yet:
    that requires a seeded system user per facility, which is
    facilities/users territory (migration 0002), not this module. This
    function keeps falling back to NULL until that row exists to point
    at — tracked as a follow-up, not silently dropped.
    """
    return _actor_var.get()

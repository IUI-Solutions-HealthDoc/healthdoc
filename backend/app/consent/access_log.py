"""
data_access_log logging dependency for patient-data GET routes.

Repo path: backend/app/consent/access_log.py

WHAT THIS IS
------------
A FastAPI dependency FACTORY — the "decorator" in the ticket, in FastAPI
terms (this repo's existing convention for this exact shape of thing is
app/common/modules.py's require_module(), whose own docstring says it
works "like require_roles" — same pattern here). Apply it to any
patient-data GET route via `dependencies=[...]`:

    from app.consent.access_log import log_patient_data_access

    router.get(
        "/patients/{patient_id}",
        dependencies=[Depends(log_patient_data_access(
            resource_type="patients",
            purpose_code="direct_treatment",
        ))],
    )
    async def get_patient(patient_id: uuid.UUID, ...): ...

Put it FIRST in a route's `dependencies=[...]` list. FastAPI dependencies
run in order; if a later dependency on the same route 404s/403s before
the handler runs, you still want the attempt logged — that's the whole
point of a "denials" column (see below).

WHY A SEPARATE SESSION + IMMEDIATE COMMIT, NOT db.flush() ON THE REQUEST
SESSION
-------------------------------------------------------------------
app/common/db.get_db() rolls back the *whole* request session on any
exception raised anywhere downstream. The schema doc says access must be
logged "including denials and break-glass emergency access" (§7). If
this dependency just db.add()'d onto the request's session, a later
403/404 would roll the log row back along with everything else — the
exact case this table exists to prove happened. So this opens its own
SessionLocal(), writes one row, commits, and closes — entirely
independent of the request's own transaction and its eventual outcome.

WHAT'S DELIBERATELY NOT DONE HERE (scope)
-------------------------------------------
This only WRITES the log row. It does not:
  - enforce consent (block the request if consent isn't granted).
    consent_required is whatever the caller passes at decoration time
    (site knowledge — e.g. False for a treating doctor's own patient,
    True for research/export access). consent_id/consent_verified ARE
    now resolved (B7-W5-01, service.find_active_consent) against a real
    granted, non-expired consent_records row for (patient_id,
    purpose_code) — but this is a read-only lookup, not an enforcement
    gate; the request proceeds either way.
  - detect break-glass automatically. emergency_access defaults False;
    a route with a genuine emergency-override path should pass
    emergency_access=True explicitly.
  - resolve which specific patient a non-patient-keyed resource belongs
    to (e.g. an order_id that isn't itself a patient_id). Callers must
    supply the right path-param name via patient_id_param.

AUTH — confirmed against app/auth/deps.py: CurrentUser =
Annotated[AuthUser, Depends(get_current_user)]. AuthUser has sub,
username, roles — no `id` field, so _resolve_user_id() always takes the
keycloak_sub lookup path.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

# Shared with audit_logs on purpose: "which role was this action taken under"
# must have one answer, not two implementations that drift. Made public in
# #329 for exactly this import.
from app.audit.deps import select_acting_role
from app.auth.deps import CurrentUser
from app.common.db import SessionLocal
from app.common.enums import AccessChannel
from app.consent.access_log_fallback import serialise_row_for_fallback, write_fallback_row
from app.consent.models import DataAccessLog
from app.consent.service import find_active_consent

logger = logging.getLogger(__name__)

# Minimal read-only projection — only needed if CurrentUser doesn't
# already carry the resolved app users.id. Same reasoning as
# app/billing/service.py's users_t / resolve_actor_user_id.
users_t = sa.table("users", sa.column("id"), sa.column("keycloak_sub"))


def log_patient_data_access(
    *,
    resource_type: str,
    purpose_code: str,
    patient_id_param: str = "patient_id",
    resource_id_param: str | None = None,
    access_channel: str = AccessChannel.API.value,
    consent_required: bool | None = None,
    emergency_access: bool = False,
) -> Callable:
    """
    Dependency factory. See module docstring for usage and the
    rollback/scope notes.

    Args:
        resource_type: what table/module this route reads (e.g.
            "patients", "encounters", "lab_results"). Free text, matches
            the "resource_type" convention already used by audit_logs.
        purpose_code: why this route reads patient data. Not a
            CheckedEnum on purpose — consent_purposes is a configurable
            lookup table (schema doc), so this stays a plain string the
            route owner chooses, same as billing's scheme_code.
        patient_id_param: name of the path (or query) param holding the
            patient's UUID on this route. Defaults to "patient_id".
        resource_id_param: name of the path/query param holding the
            specific resource's UUID, if different from patient_id_param
            (e.g. an encounter_id on a route nested under a patient).
            Defaults to patient_id_param's value.
        access_channel: AccessChannel value — defaults to "api".
        consent_required: caller's call on whether this purpose needs
            explicit consent (per schema doc's implicit/explicit rules).
            Left None if unknown/not yet decided for this route.
        emergency_access: set True only on a route that is itself a
            break-glass path.
    """

    async def _log_access(request: Request, user: CurrentUser) -> None:
        patient_id = _extract_uuid(request, patient_id_param)
        resource_id = (
            _extract_uuid(request, resource_id_param) if resource_id_param else patient_id
        )
        role = select_acting_role(user.roles)

        if patient_id is None:
            # Wiring mistake (decorated route doesn't actually have this
            # path/query param), not a runtime condition — but per
            # review, this must still be RECORDED, not just logged and
            # dropped: a clinical read happened and normal logging
            # couldn't place it. Goes straight to the durable fallback
            # rather than attempting a DB insert with no patient_id.
            row = serialise_row_for_fallback(
                user_id=None,
                role=role,
                resource_type=resource_type,
                resource_id=resource_id,
                patient_id=None,
                purpose_code=purpose_code,
                access_channel=access_channel,
                emergency_access=emergency_access,
                consent_required=consent_required,
                consent_verified=None,
            )
            await write_fallback_row(
                row,
                failure_reason=(
                    f"missing_path_param:{patient_id_param} on {request.method} {request.url.path}"
                ),
            )
            logger.error(
                "log_patient_data_access: no param '%s' found on %s %s — "
                "wrote to fallback instead of data_access_log. Check the "
                "dependency wiring on this route.",
                patient_id_param, request.method, request.url.path,
            )
            return

        try:
            async with SessionLocal() as log_session:
                user_id = await _resolve_user_id(log_session, user)
                if user_id is None:
                    row = serialise_row_for_fallback(
                        user_id=None,
                        role=role,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        patient_id=patient_id,
                        purpose_code=purpose_code,
                        access_channel=access_channel,
                        emergency_access=emergency_access,
                        consent_required=consent_required,
                        consent_verified=None,
                    )
                    await write_fallback_row(row, failure_reason="unresolved_user_id")
                    logger.error(
                        "log_patient_data_access: could not resolve a users.id "
                        "for this request (%s %s) — wrote to fallback instead "
                        "of data_access_log.",
                        request.method, request.url.path,
                    )
                    return

                # B7-W5-01: resolve the patient's active granted consent
                # for this purpose_code, if any. consent_verified is True
                # only when a real matching grant was found -- False when
                # one was required but missing, None when not required
                # and none found (not "no", just "not applicable").
                consent = await find_active_consent(
                    log_session, patient_id=patient_id, purpose_code=purpose_code
                )
                consent_verified = True if consent else (False if consent_required else None)

                log_session.add(
                    DataAccessLog(
                        user_id=user_id,
                        role=role,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        patient_id=patient_id,
                        purpose_code=purpose_code,
                        access_channel=access_channel,
                        emergency_access=emergency_access,
                        consent_id=consent.id if consent else None,
                        consent_required=consent_required,
                        consent_verified=consent_verified,
                    )
                )
                await log_session.commit()
        except Exception as exc:
            # Logging must never be the reason a clinical read fails.
            # Losing the row silently is what changed here though: the
            # DB write failed, so this falls back to a durable local
            # write instead of just logger.exception() — see
            # access_log_fallback.py's module docstring for why a local
            # file survives failure modes a Postgres outbox wouldn't.
            row = serialise_row_for_fallback(
                user_id=None,  # not resolved on this path — DB was unreachable
                role=role,
                resource_type=resource_type,
                resource_id=resource_id,
                patient_id=patient_id,
                purpose_code=purpose_code,
                access_channel=access_channel,
                emergency_access=emergency_access,
                consent_required=consent_required,
                consent_verified=None,
            )
            await write_fallback_row(row, failure_reason=f"db_write_failed:{exc!r}")
            logger.warning(
                "data_access_log DB write failed for %s %s (patient=%s, purpose=%s) — "
                "wrote to durable fallback instead. See fallback file for recovery.",
                request.method, request.url.path, patient_id, purpose_code,
            )

    return _log_access


def _extract_uuid(request: Request, param_name: str) -> uuid.UUID | None:
    raw = request.path_params.get(param_name) or request.query_params.get(param_name)
    if raw is None:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


async def _resolve_user_id(db: AsyncSession, user: CurrentUser) -> uuid.UUID | None:
    """users.id (app UUID), not the Keycloak sub. AuthUser has no `id`
    field today, so this always falls through to the keycloak_sub lookup."""
    existing = getattr(user, "id", None)
    if existing is not None:
        return existing
    sub = getattr(user, "sub", None)
    if sub is None:
        return None
    result = await db.execute(sa.select(users_t.c.id).where(users_t.c.keycloak_sub == sub))
    return result.scalar_one_or_none()

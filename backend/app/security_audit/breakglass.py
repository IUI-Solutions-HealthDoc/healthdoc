"""Break-glass emergency access (B1-W4-01).

Lets an authorized emergency clinician bypass the normal consent gate for a patient,
under strict controls:
  - MFA-gated (caller must have amr=otp in their token; enforced by require_mfa)
  - written justification required (≥20 characters, enforced by Pydantic AND DB CHECK)
  - time-boxed: a 2-hour grant window
  - every use written to data_access_log with emergency_access=true (triggers review)
  - dual notification: patient + compliance/DPO (via notifications module)
  - grant stored in break_glass_grants for compliance review

This does NOT return clinical data itself — it mints a short-lived grant that the
history/read endpoints honour (they check for an active break_glass grant when consent
is absent).
"""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AuthUser, get_current_user, require_roles
from app.common.db import get_db
from app.consent.models import BreakGlassGrant
from app.consent.service import evaluate_clinical_access, find_active_break_glass_grant
from app.patients.models import Patient

log = logging.getLogger("healthdoc.breakglass")

router = APIRouter(prefix="/break-glass", tags=["security"])
GRANT_WINDOW = timedelta(hours=2)


def require_mfa(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
    # Keycloak puts the auth method reference in the token; MFA => 'otp' present.
    if "otp" not in getattr(user, "amr", []) and "mfa" not in getattr(user, "amr", []):
        raise HTTPException(403, {"code": "mfa_required", "detail": "Break-glass needs MFA"})
    return user


class BreakGlassRequest(BaseModel):
    patient_id: uuid.UUID
    justification: str = Field(min_length=20)

    @field_validator("justification")
    @classmethod
    def justification_long_enough(cls, v: str) -> str:
        if len(v.strip()) < 20:
            raise ValueError("justification must be at least 20 characters (non-whitespace)")
        return v.strip()


def _grant_payload(grant: BreakGlassGrant, *, reused: bool = False) -> dict:
    return {
        "id": str(grant.id),
        "patient_id": str(grant.patient_id),
        "granted_to_user_id": str(grant.granted_to_user_id),
        "justification": grant.justification,
        "granted_at": grant.granted_at.isoformat(),
        "expires_at": grant.expires_at.isoformat(),
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "revoked_by": str(grant.revoked_by) if grant.revoked_by else None,
        "reviewed_at": grant.reviewed_at.isoformat() if grant.reviewed_at else None,
        "reviewed_by": str(grant.reviewed_by) if grant.reviewed_by else None,
        "review_outcome": grant.review_outcome,
        "granted": True,
        "reused": reused,
    }


@router.get(
    "/access/{patient_id}",
    dependencies=[Depends(require_roles("emergency", "doctor"))],
)
async def access_status(
    patient_id: uuid.UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the server's consent-or-grant decision without clinical data."""
    actor = await _actor(db, user)
    patient = await db.get(Patient, patient_id)
    if (
        patient is None
        or patient.deleted_at is not None
        or patient.facility_id != actor["facility_id"]
    ):
        raise HTTPException(404, {"code": "patient_not_found"})

    decision = await evaluate_clinical_access(
        db,
        patient_id=patient_id,
        user_id=actor["id"],
    )
    response = {
        "patient_id": str(patient_id),
        "allowed": decision.allowed,
    }
    if decision.blocked_reason:
        response["blocked_reason"] = decision.blocked_reason
    if decision.grant:
        response["grant"] = _grant_payload(decision.grant)
    return response


@router.post(
    "",
    dependencies=[Depends(require_roles("emergency", "doctor")), Depends(require_mfa)],
)
async def break_glass(
    payload: BreakGlassRequest,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    expires = now + GRANT_WINDOW
    caller = await _actor(db, user)
    patient = await db.get(Patient, payload.patient_id)
    if (
        patient is None
        or patient.deleted_at is not None
        or patient.facility_id != caller["facility_id"]
    ):
        raise HTTPException(404, "Patient not found in caller facility")

    # Serialize same-clinician/same-patient creation. Without this lock two
    # simultaneous browser retries can both observe "no active grant" before
    # either inserts, producing duplicate grants and notifications.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"break-glass:{caller['id']}:{payload.patient_id}"},
    )
    active = await find_active_break_glass_grant(
        db,
        patient_id=payload.patient_id,
        user_id=caller["id"],
    )
    if active is not None:
        return _grant_payload(active, reused=True)

    # 1) Store the grant in break_glass_grants for compliance tracking
    #    A grant is active iff now() < expires_at AND revoked_at IS NULL
    grant = BreakGlassGrant(
        id=uuid.uuid4(),
        patient_id=payload.patient_id,
        granted_to_user_id=caller["id"],
        justification=payload.justification,
        granted_at=now,
        expires_at=expires,
    )
    db.add(grant)
    await db.flush()

    # 2) Audit the access attempt (emergency_access=true => mandatory review)
    await db.execute(text("""
        INSERT INTO data_access_log
            (id, user_id, role, resource_type, patient_id, purpose_code,
             access_channel, emergency_access, consent_required, consent_verified, accessed_at)
        VALUES (uuid_generate_v4(), :uid, :role, 'patient', :pid, 'break_glass',
                'api', true, true, false, :ts)
    """), {"uid": caller["id"], "role": (user.roles or [None])[0],
           "pid": payload.patient_id, "ts": now})

    # 3) Dual notification (patient + compliance) — enqueued via notifications
    for target in ("patient", "compliance"):
        await db.execute(text("""
            INSERT INTO notification_history
                (id, event_type, payload, facility_id, created_at)
            VALUES (uuid_generate_v4(), 'break_glass_used',
                    CAST(:p AS jsonb), :fid, :ts)
        """), {"p": json.dumps({"target": target,
                               "patient_id": str(payload.patient_id),
                               "by": user.username,
                               "expires_at": expires.isoformat()}),
               "fid": caller["facility_id"],
               "ts": now})

    return _grant_payload(grant)


@router.get("/expired-unreviewed", dependencies=[Depends(require_roles("auditor", "admin"))])
async def expired_unreviewed_grants(
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Compliance worklist: grants that expired without being reviewed."""
    actor = await _actor(db, user)
    rows = (await db.execute(text("""
        SELECT g.id, g.patient_id, g.granted_to_user_id, g.justification,
               g.expires_at, g.created_at
        FROM break_glass_grants g
        JOIN patients p ON p.id = g.patient_id
        WHERE p.facility_id = :fid
          AND g.expires_at < now()
          AND g.revoked_at IS NULL
          AND g.reviewed_at IS NULL
        ORDER BY g.expires_at DESC
    """), {"fid": actor["facility_id"]})).mappings().all()
    return {"items": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Revoke and review — the two halves of this control that had columns and no
# code.
#
# break_glass_grants has carried revoked_at/revoked_by and
# reviewed_at/reviewed_by/review_outcome since 0004. Nothing wrote any of them.
#
# The consequence was not cosmetic. /expired-unreviewed is a compliance
# worklist of grants awaiting review — and with no way to record a review, that
# list could only ever grow. A worklist nobody can clear is indistinguishable
# from one nobody is working.
#
# Revocation was the other gap: a grant ran its full two hours regardless. If a
# clinician opened emergency access to the wrong patient, or the emergency
# ended, there was no way to cut it short.
# ---------------------------------------------------------------------------


async def _actor(db: AsyncSession, user: AuthUser) -> dict:
    """The caller's users row.

    break_glass_grants.revoked_by / reviewed_by are FKs to users.id. The token
    carries a Keycloak subject, which is a different identifier — the same trap
    app/billing/service.resolve_actor_user_id exists to document.
    """
    caller = (await db.execute(
        text("SELECT id, facility_id FROM users WHERE keycloak_sub = :sub"),
        {"sub": user.sub},
    )).mappings().one_or_none()
    if caller is None:
        raise HTTPException(403, "Authenticated user has no HealthDoc profile")
    return dict(caller)


class BreakGlassReview(BaseModel):
    """A compliance decision on a used grant."""

    outcome: str = Field(
        description="justified | not_justified — the reviewer's finding.",
    )
    notes: str | None = None

    @field_validator("outcome")
    @classmethod
    def _known_outcome(cls, v: str) -> str:
        if v not in ("justified", "not_justified"):
            raise ValueError("outcome must be 'justified' or 'not_justified'")
        return v


class BreakGlassRevoke(BaseModel):
    reason: str = Field(
        min_length=1,
        description="Why the grant is being cut short. Recorded on the row — a "
                    "revocation with no reason is not reviewable later.",
    )


@router.post("/{grant_id}/revoke",
             dependencies=[Depends(require_roles("emergency", "doctor", "admin"))])
async def revoke_grant(
    grant_id: uuid.UUID,
    payload: BreakGlassRevoke,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """End an active grant now rather than at its two-hour expiry.

    Only an ACTIVE grant can be revoked. An already-expired one is not revoked,
    it is over — recording a revocation against it would misstate when access
    actually stopped, which is the one fact this row exists to establish.

    Idempotency is deliberate rather than incidental: revoking twice returns
    409, because the second call would move revoked_at forward and quietly
    extend the recorded access window.
    """
    # revoked_by is an FK to users.id — the app-side UUID, NOT the Keycloak
    # subject. Resolved the same way the grant endpoint above does; writing
    # user.sub here would violate the foreign key.
    actor = await _actor(db, user)

    # Scoped through the patient, because break_glass_grants has no
    # facility_id. Revoking another hospital's emergency grant is not this
    # caller's to do, and 404 rather than 403 keeps grant ids unenumerable.
    row = (await db.execute(text("""
        SELECT g.id, g.revoked_at, g.expires_at
        FROM break_glass_grants g
        JOIN patients p ON p.id = g.patient_id
        WHERE g.id = :id AND p.facility_id = :fid
          AND (:can_revoke_any OR g.granted_to_user_id = :actor)
    """), {
        "id": grant_id,
        "fid": actor["facility_id"],
        "actor": actor["id"],
        "can_revoke_any": "admin" in user.roles,
    })).mappings().one_or_none()

    if row is None:
        raise HTTPException(404, {"code": "grant_not_found"})
    if row["revoked_at"] is not None:
        raise HTTPException(409, {"code": "already_revoked",
                                  "message": "This grant was already revoked."})
    if row["expires_at"] <= datetime.now(timezone.utc):
        raise HTTPException(409, {
            "code": "already_expired",
            "message": "This grant has already expired; there is nothing to revoke.",
        })

    await db.execute(text("""
        UPDATE break_glass_grants
        SET revoked_at = now(), revoked_by = :actor, updated_at = now()
        WHERE id = :id
    """), {"id": grant_id, "actor": actor["id"]})
    await db.commit()

    log.info("break_glass_revoked grant=%s by=%s reason=%s",
             grant_id, user.sub, payload.reason)
    return {"revoked": True, "grant_id": grant_id}


@router.post("/{grant_id}/review",
             dependencies=[Depends(require_roles("auditor", "admin"))])
async def review_grant(
    grant_id: uuid.UUID,
    payload: BreakGlassReview,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record the compliance review of a grant.

    This is what clears a row off /expired-unreviewed. Without it that worklist
    could only grow, which is worse than having no worklist: it looks like a
    control while guaranteeing a backlog.

    Reviewed once, and only once — a second review would overwrite the first
    reviewer's finding with no trace that it changed.
    """
    # reviewed_by is an FK to users.id, not the Keycloak subject — see revoke.
    actor = await _actor(db, user)

    row = (await db.execute(text("""
        SELECT g.id, g.reviewed_at
        FROM break_glass_grants g
        JOIN patients p ON p.id = g.patient_id
        WHERE g.id = :id AND p.facility_id = :fid
    """), {"id": grant_id, "fid": actor["facility_id"]})).mappings().one_or_none()

    if row is None:
        raise HTTPException(404, {"code": "grant_not_found"})
    if row["reviewed_at"] is not None:
        raise HTTPException(409, {
            "code": "already_reviewed",
            "message": "This grant has already been reviewed. A second review "
                       "would overwrite the first finding.",
        })

    await db.execute(text("""
        UPDATE break_glass_grants
        SET reviewed_at = now(), reviewed_by = :actor, review_outcome = :outcome,
            updated_at = now()
        WHERE id = :id
    """), {"id": grant_id, "actor": actor["id"], "outcome": payload.outcome})
    await db.commit()

    log.info("break_glass_reviewed grant=%s by=%s outcome=%s",
             grant_id, user.sub, payload.outcome)
    return {"reviewed": True, "grant_id": grant_id, "outcome": payload.outcome}

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
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AuthUser, get_current_user, require_roles
from app.common.db import get_db

router = APIRouter(prefix="/break-glass", tags=["security"])
GRANT_WINDOW = timedelta(hours=2)


def require_mfa(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
    # Keycloak puts the auth method reference in the token; MFA => 'otp' present.
    if "otp" not in getattr(user, "amr", []) and "mfa" not in getattr(user, "amr", []):
        raise HTTPException(403, {"code": "mfa_required", "detail": "Break-glass needs MFA"})
    return user


class BreakGlassRequest(BaseModel):
    patient_id: str
    justification: str = Field(min_length=20)

    @field_validator("justification")
    @classmethod
    def justification_long_enough(cls, v: str) -> str:
        if len(v.strip()) < 20:
            raise ValueError("justification must be at least 20 characters (non-whitespace)")
        return v.strip()


@router.post("", dependencies=[Depends(require_roles("emergency", "doctor")),
                               Depends(require_mfa)])
async def break_glass(payload: BreakGlassRequest,
                      user: Annotated[AuthUser, Depends(get_current_user)],
                      db: AsyncSession = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    expires = now + GRANT_WINDOW
    caller = (await db.execute(text("SELECT id, facility_id FROM users WHERE keycloak_sub = :sub"),
                               {"sub": user.sub})).mappings().one_or_none()
    if caller is None:
        raise HTTPException(403, "Authenticated user has no HealthDoc profile")
    exists = (await db.execute(text("SELECT 1 FROM patients WHERE id = :pid AND facility_id = :fid"),
                               {"pid": payload.patient_id, "fid": caller["facility_id"]})).scalar_one_or_none()
    if exists is None:
        raise HTTPException(404, "Patient not found in caller facility")
    active = (await db.execute(text("""
        SELECT expires_at FROM break_glass_grants
        WHERE patient_id = :pid AND granted_to_user_id = :uid
          AND expires_at > now() AND revoked_at IS NULL
        ORDER BY expires_at DESC LIMIT 1
    """), {"pid": payload.patient_id, "uid": caller["id"]})).mappings().one_or_none()
    if active is not None:
        return {"granted": True, "patient_id": payload.patient_id,
                "expires_at": active["expires_at"].isoformat(), "reused": True}

    # 1) Store the grant in break_glass_grants for compliance tracking
    #    A grant is active iff now() < expires_at AND revoked_at IS NULL
    await db.execute(text("""
        INSERT INTO break_glass_grants
            (id, patient_id, granted_to_user_id, justification, granted_at, expires_at, created_at)
        VALUES (uuid_generate_v4(), :pid, :uid, :justification, :ts, :expires, :ts)
    """), {"pid": payload.patient_id, "uid": caller["id"],
           "justification": payload.justification,
           "expires": expires, "ts": now})

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
                               "patient_id": payload.patient_id,
                               "by": user.username,
                               "expires_at": expires.isoformat()}),
               "fid": caller["facility_id"],
               "ts": now})

    return {"granted": True, "patient_id": payload.patient_id,
            "expires_at": expires.isoformat(),
            "justification_logged": True}


@router.get("/expired-unreviewed", dependencies=[Depends(require_roles("auditor", "dpo", "admin"))])
async def expired_unreviewed_grants(
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Compliance worklist: grants that expired without being reviewed."""
    rows = (await db.execute(text("""
        SELECT id, patient_id, granted_to_user_id, justification, expires_at, created_at
        FROM break_glass_grants
        WHERE expires_at < now() AND revoked_at IS NULL AND reviewed_at IS NULL
        ORDER BY expires_at DESC
    """))).mappings().all()
    return {"items": [dict(r) for r in rows]}

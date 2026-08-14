"""ABHA capture endpoint (B1-W6-01).

Captures/links an ABHA to a patient: verifies with the ABDM gateway (graceful
degradation if unreachable), stores the returned linking token ENCRYPTED
(key-versioned, common/security.py), and enqueues an outbox event so the link
syncs to the cloud. Never stores the token in plaintext.

Follows the same graceful-degradation pattern as integrations/icd11/client.py:
a rural facility going offline must not break registration.
"""
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AuthUser, get_current_user, require_roles
from app.common.config import get_settings
from app.common.db import get_db
from app.common.security import encrypt_pii
from app.outbox.service import enqueue

log = logging.getLogger("healthdoc.abdm")
router = APIRouter(prefix="/abdm/abha", tags=["abdm"])


class AbhaCapture(BaseModel):
    patient_id: str
    abha_number: str
    linking_token: str        # from ABDM; encrypted before storage, never persisted raw


async def _verify_with_gateway(abha_number: str) -> dict | None:
    """Verify ABHA with ABDM gateway. Returns None if gateway is unreachable
    (graceful degradation — offline facility must not break registration).
    No PHI in logs, including on error paths."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{settings.abdm_gateway_base_url}/v3/hip/token/on-generate",
                headers={
                    "X-CM-ID": "sbx",
                    "Authorization": f"Bearer {settings.abdm_client_secret}",
                },
                json={"abhaNumber": abha_number},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        log.warning("ABDM gateway unreachable — proceeding offline (graceful degradation)")
        return None
    except httpx.TimeoutException:
        log.warning("ABDM gateway timeout — proceeding offline (graceful degradation)")
        return None
    except httpx.HTTPStatusError as exc:
        # No PHI in logs: log status only, not the body which may contain patient data
        log.warning("ABDM gateway returned %s — proceeding offline", exc.response.status_code)
        return None
    except Exception:
        log.exception("Unexpected ABDM gateway error — proceeding offline")
        return None


@router.post("/link", dependencies=[Depends(require_roles("receptionist", "doctor"))])
async def link_abha(payload: AbhaCapture,
                    user: Annotated[AuthUser, Depends(get_current_user)],
                    db: AsyncSession = Depends(get_db)) -> dict:
    user_row = (await db.execute(
        text("SELECT id, facility_id FROM users WHERE keycloak_sub = :sub"),
        {"sub": user.sub},
    )).mappings().one_or_none()
    if user_row is None:
        raise HTTPException(403, "Authenticated user has no HealthDoc profile")

    # Try verifying with ABDM — gracefully degrade if gateway is down
    gateway_result = await _verify_with_gateway(payload.abha_number)
    gateway_verified = gateway_result is not None

    blob, key_version = encrypt_pii(payload.linking_token)
    result = await db.execute(text("""
        UPDATE patients
        SET abha_number = :abha,
            abha_linking_token_encrypted = :blob,
            abha_linking_key_version = :kv,
            abha_linked_at = now(), updated_at = now(), updated_by = :uid,
            identity_status = CASE WHEN :verified THEN identity_status ELSE 'identity_unverified' END
        WHERE id = :pid AND facility_id = :facility_id
    """), {"abha": payload.abha_number, "blob": blob, "kv": key_version,
           "pid": payload.patient_id, "uid": user_row["id"],
           "facility_id": user_row["facility_id"], "verified": gateway_verified})
    if result.rowcount != 1:
        raise HTTPException(404, "Patient not found in caller facility")
    await enqueue(db, aggregate_type="patient", aggregate_id=payload.patient_id,
                  event_type="abha_linked", payload={"abha_number": payload.abha_number},
                  sensitivity="important")
    return {"patient_id": payload.patient_id, "abha_linked": True,
            "gateway_verified": gateway_verified}

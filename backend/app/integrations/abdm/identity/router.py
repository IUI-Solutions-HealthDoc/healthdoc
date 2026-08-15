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

import uuid

from sqlalchemy import select

from app.auth.deps import AuthUser, CurrentDbUser, get_current_user, require_roles
from app.common.config import get_settings
from app.common.db import get_db
from app.common.security import encrypt_pii
from app.outbox.service import enqueue
from app.patients.models import Patient

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



class AbhaOut(BaseModel):
    patient_id: uuid.UUID
    abha_number: str | None

    model_config = {"from_attributes": True}


def _normalise_abha(raw: str) -> str:
    """ABHA numbers are quoted with or without hyphens; store one form."""
    return raw.replace("-", "").strip()


async def _get_patient_or_404(
    db: AsyncSession, patient_id: uuid.UUID, facility_id: uuid.UUID
) -> Patient:
    """404 rather than 403 for another facility's patient — a 403 confirms the
    row exists, which is enough to probe for patients across facilities."""
    patient = await db.get(Patient, patient_id)
    if patient is None or patient.facility_id != facility_id:
        raise HTTPException(404, {"code": "patient_not_found"})
    return patient


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

    # An ABHA belongs to exactly one person. patients.abha_number is UNIQUE, so
    # without this the collision surfaces as an IntegrityError 500 rather than
    # something a receptionist can act on.
    normalised = _normalise_abha(payload.abha_number)
    clash = (await db.execute(
        select(Patient.id).where(
            Patient.abha_number == normalised,
            Patient.id != payload.patient_id,
        )
    )).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(409, {
            "code": "duplicate_abha",
            "message": "This ABHA number is already linked to another patient",
        })

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


@router.get(
    "/patients/{patient_id}/abha",
    response_model=AbhaOut,
    dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "admin"))],
)
async def get_abha(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> AbhaOut:
    """Read a patient's linked ABHA. Facility-scoped via _get_patient_or_404."""
    patient = await _get_patient_or_404(db, patient_id, current_db_user.facility_id)
    return AbhaOut(patient_id=patient.id, abha_number=patient.abha_number)


@router.delete(
    "/patients/{patient_id}/abha",
    response_model=AbhaOut,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def unlink_abha(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> AbhaOut:
    """Unlink an ABHA, clearing the encrypted token with it.

    All three columns go together. Clearing abha_number alone would leave
    abha_linking_token_encrypted and abha_linking_key_version populated — an
    encrypted ABDM token for a link that no longer exists, which is the exact
    half-record state 0030's both-or-neither CHECK exists to prevent, and a
    DPDP problem besides: we would be retaining an identity credential after
    the relationship it belonged to was severed.
    """
    patient = await _get_patient_or_404(db, patient_id, current_db_user.facility_id)

    if patient.abha_number is None:
        raise HTTPException(409, {
            "code": "no_abha_linked",
            "message": "Patient has no ABHA number linked",
        })

    patient.abha_number = None
    patient.abha_linking_token_encrypted = None
    patient.abha_linking_key_version = None
    patient.abha_linked_at = None
    patient.updated_by = current_db_user.id
    await db.flush()

    await enqueue(
        db,
        aggregate_type="patient",
        aggregate_id=str(patient.id),
        event_type="abha_unlinked",
        payload={},
        sensitivity="important",
    )
    await db.refresh(patient)
    return AbhaOut(patient_id=patient.id, abha_number=None)

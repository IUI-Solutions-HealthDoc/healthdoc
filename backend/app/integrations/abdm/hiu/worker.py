"""Retry HIU receipt notification without rolling back or re-decrypting data."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.common.config import get_settings
from app.common.db import SessionLocal
from app.integrations.abdm.hiu import gateway, records
from app.integrations.abdm.hiu.models import (
    AbdmConsentRequest,
    AbdmHiuConsentArtefact,
    AbdmHiuHealthInformationRequest,
    AbdmReceivedBundle,
)
from app.integrations.abdm.jobs import AbdmJob
from app.users.models import Facility


async def _require_configured_facility(db, job: AbdmJob) -> None:
    # Gateway helpers use a single configured HIU identity. Facility-scoped
    # rows must not be sent under that identity for any other hospital.
    configured = get_settings().abdm_hfr_facility_id
    facility = await db.get(Facility, job.facility_id)
    if (
        not configured
        or configured == "change-me"
        or facility is None
        or not facility.is_active
        or facility.hfr_facility_id != configured
    ):
        raise ValueError("Facility is not configured for this bridge")


async def dispatch(job: AbdmJob) -> None:
    if job.kind == "hiu_notify":
        await notify_received(job)
        return
    async with SessionLocal() as db:
        await _require_configured_facility(db, job)
        if job.kind == "hiu_fetch":
            artefact = await db.get(AbdmHiuConsentArtefact, job.target_id)
            if artefact is None or artefact.facility_id != job.facility_id:
                raise ValueError("Consent artefact unavailable")
            if artefact.status != "granted" or artefact.expires_at is not None:
                return  # Revoked or already fetched; never restore an ended grant.
            consent = await db.get(AbdmConsentRequest, artefact.consent_request_id)
            if (
                consent is None
                or consent.status != "granted"
                or consent.facility_id != job.facility_id
            ):
                return
            await gateway.fetch_consent_artefact(
                consent_id=artefact.consent_artefact_id, request_id=str(job.id)
            )
        elif job.kind == "hiu_consent":
            row = await db.get(AbdmConsentRequest, job.target_id)
            if row is None or row.facility_id != job.facility_id:
                raise ValueError("Consent request unavailable")
            if row.status != "requested" or row.consent_request_id:
                return
            from app.patients.models import Patient

            patient = await db.get(Patient, row.patient_id)
            if (
                patient is None
                or patient.facility_id != job.facility_id
                or patient.abha_address != row.abha_address
                or patient.abha_linked_at is None
                or patient.deleted_at is not None
                or patient.merged_into_patient_id is not None
                or records.aware(row.requested_expiry) <= datetime.now(UTC)
            ):
                raise ValueError("Verified patient binding or request expired")
            _, response = await gateway.request_consent(
                abha_address=row.abha_address,
                hi_types=row.hi_types,
                date_from=row.date_range_from,
                date_to=row.date_range_to,
                expiry=row.requested_expiry,
                purpose=gateway.PURPOSE_CARE_MANAGEMENT,
                request_id=row.gateway_request_id,
            )
            body = response.body if isinstance(response.body, dict) else {}
            remote_id = body.get("consentRequestId") or body.get("id")
            await db.refresh(row)  # A fast callback may already have arrived.
            if isinstance(remote_id, str) and row.consent_request_id is None:
                row.consent_request_id = remote_id
                await db.commit()
        elif job.kind == "hiu_request":
            row = await db.get(AbdmHiuHealthInformationRequest, job.target_id)
            if row is None or row.facility_id != job.facility_id:
                raise ValueError("Data request unavailable")
            if row.status != "requested" or row.transaction_id:
                return
            grant = await records.grant_for(db, row, now=datetime.now(UTC))
            if (
                row.private_key_encrypted is None
                or records.aware(row.key_expires_at) <= datetime.now(UTC)
                or grant.artefact.date_range_from is None
                or grant.artefact.date_range_to is None
            ):
                raise ValueError("Transfer key or consent range unavailable")
            await gateway.request_health_information(
                consent_id=grant.artefact.consent_artefact_id,
                date_from=grant.artefact.date_range_from,
                date_to=grant.artefact.date_range_to,
                dh_public_key=row.public_key_b64,
                key_expiry=row.key_expires_at,
                nonce=row.nonce_b64,
                request_id=row.gateway_request_id,
            )
        else:
            raise ValueError("Unsupported HIU work")


async def notify_received(job: AbdmJob) -> None:
    async with SessionLocal() as db:
        await _require_configured_facility(db, job)
        request = await db.get(AbdmHiuHealthInformationRequest, job.target_id)
        if (
            request is None
            or request.facility_id != job.facility_id
            or request.status != "received"
        ):
            raise ValueError("No completed receive transaction")
        artefact = await db.get(AbdmHiuConsentArtefact, request.artefact_id)
        if artefact is None or artefact.facility_id != job.facility_id:
            raise ValueError("Consent unavailable")
        raw = artefact.raw_artefact
        detail = raw.get("consentDetail", {}) if isinstance(raw, dict) else {}
        hip = detail.get("hip", {}) if isinstance(detail, dict) else {}
        if not isinstance(hip, dict) or not isinstance(hip.get("id"), str) or not hip["id"]:
            raise ValueError("Source HIP unknown")
        references = (
            (
                await db.execute(
                    select(AbdmReceivedBundle.care_context_reference)
                    .where(
                        AbdmReceivedBundle.hi_request_id == request.id,
                        AbdmReceivedBundle.facility_id == job.facility_id,
                        AbdmReceivedBundle.status == "stored",
                    )
                    .order_by(AbdmReceivedBundle.page_number, AbdmReceivedBundle.entry_index)
                )
            )
            .scalars()
            .all()
        )
        await gateway.notify_hi_receipt(
            consent_id=artefact.consent_artefact_id,
            transaction_id=request.transaction_id,
            session_status="TRANSFERRED",
            hip_id=hip["id"],
            request_id=str(job.id),
            status_responses=[
                {
                    "careContextReference": reference,
                    "hiStatus": "OK",
                    "description": "Received and authenticated",
                }
                for reference in dict.fromkeys(references)
            ],
        )

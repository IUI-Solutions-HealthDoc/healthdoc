"""HIP health-information bundle assembly and direct delivery to an HIU.

ABDM brokers the request but does not carry the clinical payload. For each
consented care context this worker builds an NRCeS FHIR document, encrypts it
to the HIU's ephemeral public key, and POSTs one independently encrypted page
to the nominated data-push URL. One context per page avoids AES-GCM nonce/key
reuse while still following ABDM's page contract.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import Admission, Discharge
from app.allergies.models import Allergy
from app.common.db import SessionLocal
from app.integrations.abdm.fhir.builder import build_clinical_bundle
from app.integrations.abdm.hip import gateway as hip_gateway
from app.integrations.abdm.hip import service as hip_service
from app.integrations.abdm.hip.models import (
    AbdmCareContext,
    AbdmHipConsentArtefact,
    AbdmHipHealthInformationRequest,
)
from app.nursing.models import Vitals
from app.opd.models import Diagnosis, Encounter, Visit
from app.orders.models import Order, Prescription, PrescriptionItem
from app.pathology.models import LabOrderItem, LabResult
from app.patients.models import Patient
from app.radiology.models import RadiologyOrderItem, RadiologyReport
from app.users.models import Facility, User

log = logging.getLogger("healthdoc.abdm.hip.transfer")

_FHIR_MEDIA = "application/fhir+json"
_MAX_ATTEMPTS = 3


class TransferError(RuntimeError):
    """A safe operational reason why a transfer could not be completed."""


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def _validate_data_push_url(raw: str) -> str:
    """Reject clear-text and internal destinations before making an HTTP call."""
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise TransferError("HIU dataPushUrl must be an HTTPS URL without user information")
    if parsed.fragment:
        raise TransferError("HIU dataPushUrl must not contain a fragment")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise TransferError("HIU dataPushUrl resolves to a local host")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host,
                parsed.port or 443,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise TransferError("HIU dataPushUrl hostname could not be resolved") from exc
        addresses = list({ipaddress.ip_address(info[4][0]) for info in infos})
    if not addresses or any(not address.is_global for address in addresses):
        raise TransferError("HIU dataPushUrl must resolve only to public addresses")
    return raw


def _result_observations(test_name: str, result_data: dict[str, Any], result_id: Any) -> list[dict]:
    observations: list[dict] = []
    for position, (name, raw) in enumerate(sorted(result_data.items())):
        if raw is None:
            continue
        value, unit = raw, None
        if isinstance(raw, dict) and "value" in raw:
            value = raw.get("value")
            unit = raw.get("unit")
        elif isinstance(raw, dict | list):
            value = json.dumps(raw, sort_keys=True, separators=(",", ":"))
        if value is None:
            continue
        observations.append(
            {
                "id": f"{result_id}:{position}",
                "name": f"{test_name} — {name}",
                "value": value,
                "unit": unit,
            }
        )
    return observations


async def _clinical_facts(
    db: AsyncSession,
    context: AbdmCareContext,
    *,
    facility: Facility,
) -> dict[str, Any]:
    """Read the exact rows that substantiate one care-context document."""
    patient = await db.get(Patient, context.patient_id)
    visit = await db.get(Visit, context.visit_id) if context.visit_id else None
    if patient is None or visit is None:
        raise TransferError("Care context is not attached to a patient visit")

    encounters = list(
        (
            await db.execute(
                select(Encounter)
                .where(Encounter.visit_id == visit.id)
                .order_by(Encounter.started_at.asc().nulls_last(), Encounter.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not encounters:
        raise TransferError("Care context has no clinical encounter")
    primary = encounters[-1]
    practitioner = await db.get(User, primary.provider_user_id)
    if practitioner is None or not practitioner.registration_number:
        raise TransferError("Encounter author has no verified registration number")
    if not facility.hfr_facility_id:
        raise TransferError("Facility has no HFR identifier")

    encounter_ids = [row.id for row in encounters]
    diagnoses = list(
        (await db.execute(select(Diagnosis).where(Diagnosis.encounter_id.in_(encounter_ids))))
        .scalars()
        .all()
    )
    allergies = list(
        (
            await db.execute(
                select(Allergy).where(
                    Allergy.patient_id == patient.id,
                    Allergy.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    vitals = list(
        (
            await db.execute(
                select(Vitals)
                .where(
                    Vitals.patient_id == patient.id,
                    Vitals.encounter_id.in_(encounter_ids),
                )
                .order_by(Vitals.measured_at.asc())
            )
        )
        .scalars()
        .all()
    )

    prescriptions = list(
        (await db.execute(select(Prescription).where(Prescription.encounter_id.in_(encounter_ids))))
        .scalars()
        .all()
    )
    prescription_ids = [row.id for row in prescriptions]
    prescription_items = (
        list(
            (
                await db.execute(
                    select(PrescriptionItem).where(
                        PrescriptionItem.prescription_id.in_(prescription_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        if prescription_ids
        else []
    )

    lab_rows = list(
        (
            await db.execute(
                select(LabOrderItem, LabResult)
                .join(Order, Order.id == LabOrderItem.order_id)
                .join(LabResult, LabResult.lab_order_item_id == LabOrderItem.id)
                .where(
                    Order.encounter_id.in_(encounter_ids),
                    LabResult.is_current.is_(True),
                    LabResult.status.in_(("final", "corrected")),
                )
            )
        ).all()
    )
    radiology_rows = list(
        (
            await db.execute(
                select(RadiologyOrderItem, RadiologyReport)
                .join(Order, Order.id == RadiologyOrderItem.order_id)
                .join(
                    RadiologyReport,
                    RadiologyReport.radiology_order_item_id == RadiologyOrderItem.id,
                )
                .where(
                    Order.encounter_id.in_(encounter_ids),
                    RadiologyReport.is_current.is_(True),
                    RadiologyReport.status.in_(("final", "corrected")),
                )
            )
        ).all()
    )

    discharge_row = (
        await db.execute(
            select(Admission, Discharge)
            .join(Discharge, Discharge.admission_id == Admission.id)
            .where(Admission.visit_id == visit.id)
        )
    ).first()

    observation_names = (
        ("height_cm", "Height", "cm"),
        ("weight_kg", "Weight", "kg"),
        ("bmi", "Body mass index", "kg/m2"),
        ("temp_c", "Body temperature", "Cel"),
        ("pulse_bpm", "Pulse rate", "/min"),
        ("resp_rate", "Respiratory rate", "/min"),
        ("bp_systolic", "Systolic blood pressure", "mm[Hg]"),
        ("bp_diastolic", "Diastolic blood pressure", "mm[Hg]"),
        ("spo2_pct", "Peripheral oxygen saturation", "%"),
        ("pain_score", "Pain score", "score"),
    )
    observations = [
        {
            "id": f"{row.id}:{attribute}",
            "name": display,
            "value": getattr(row, attribute),
            "unit": unit,
            "effective": row.measured_at,
        }
        for row in vitals
        for attribute, display, unit in observation_names
        if getattr(row, attribute) is not None
    ]
    medications = [
        {
            "id": item.id,
            "name": item.medicine_name,
            "dosage": item.dosage,
            "frequency": item.frequency,
            "route": item.route,
            "instructions": item.instructions,
        }
        for item in prescription_items
    ]
    reports = [
        {
            "id": result.id,
            "kind": "lab",
            "test_code": item.test_code,
            "name": item.test_name,
            "issued": result.created_at,
            "conclusion": result.remarks,
            "observations": _result_observations(
                item.test_name, result.result_data or {}, result.id
            ),
        }
        for item, result in lab_rows
    ]
    reports.extend(
        {
            "id": report.id,
            "kind": "radiology",
            "modality": item.modality,
            "pacs_study_uid": item.pacs_study_uid,
            "name": item.scan_type,
            "issued": report.created_at,
            "conclusion": "\n\n".join(
                value for value in (report.findings, report.impression) if value
            ),
            "observations": [],
        }
        for item, report in radiology_rows
    )

    note_parts = []
    for label, value in (
        ("Subjective", primary.subjective),
        ("Objective", primary.objective),
        ("Assessment", primary.assessment),
        ("Plan", primary.plan),
    ):
        if value:
            note_parts.append(f"{label}: {value}")
    authored_at = _aware(
        primary.ended_at or primary.started_at or visit.visit_date
    ) or datetime.now(UTC)
    encounter_status = "discharged" if discharge_row else visit.status
    encounter_class = "IMP" if discharge_row else "AMB"

    common = {
        "patient": {
            "id": patient.id,
            "name": patient.full_name,
            "identifier": patient.uhid or patient.thid,
            "abha_number": patient.abha_number,
            "gender": patient.sex,
            "birth_date": patient.dob,
            "mobile": patient.mobile,
        },
        "practitioner": {
            "id": practitioner.id,
            "name": practitioner.full_name,
            "registration_number": practitioner.registration_number,
        },
        "organization": {
            "id": facility.id,
            "name": facility.name,
            "hfr_id": facility.hfr_facility_id,
        },
        "encounter": {
            "id": visit.id,
            "status": encounter_status,
            "class": encounter_class,
            "patient_name": patient.full_name,
            "start": visit.visit_date,
            "end": discharge_row[1].discharged_at if discharge_row else primary.ended_at,
        },
        "authored_at": authored_at,
        "care_context_reference": context.reference,
        "chief_complaints": [
            {"id": row.id, "text": row.chief_complaint} for row in encounters if row.chief_complaint
        ],
        "diagnoses": [
            {
                "id": row.id,
                "text": row.diagnosis_text,
                "code": row.icd_code,
                "system": "http://hl7.org/fhir/sid/icd-10",
            }
            for row in diagnoses
        ],
        "allergies": [
            {
                "id": row.id,
                "substance": row.substance_text,
                "reaction": row.reaction,
                "status": row.status,
            }
            for row in allergies
        ],
        "observations": observations,
        "medications": medications,
        "diagnostic_reports": reports,
    }

    if context.hi_type == "OPConsultation":
        common["care_plan"] = "\n".join(note_parts) or None
    elif context.hi_type == "Prescription":
        common.update(
            chief_complaints=[],
            diagnoses=[],
            allergies=[],
            observations=[],
            diagnostic_reports=[],
            care_plan=None,
        )
    elif context.hi_type == "DiagnosticReport":
        common.update(
            chief_complaints=[],
            diagnoses=[],
            allergies=[],
            observations=[],
            medications=[],
            care_plan=None,
        )
    elif context.hi_type == "DischargeSummary":
        if discharge_row is None or not discharge_row[1].discharge_summary:
            raise TransferError("Discharge context has no signed discharge summary")
        common["care_plan"] = discharge_row[1].discharge_summary
    elif context.hi_type == "WellnessRecord":
        common.update(
            chief_complaints=[],
            diagnoses=[],
            allergies=[],
            medications=[],
            diagnostic_reports=[],
            care_plan=None,
        )
    else:
        raise TransferError(f"No clinical mapper exists for HI type {context.hi_type}")
    return common


def _hiu_key_material(row: AbdmHipHealthInformationRequest) -> tuple[str, str, str]:
    material = row.hiu_key_material or {}
    public = material.get("dhPublicKey") or {}
    key_value, nonce, expiry = public.get("keyValue"), material.get("nonce"), public.get("expiry")
    if not all(isinstance(value, str) and value for value in (key_value, nonce, expiry)):
        raise TransferError("HIU key material is incomplete")
    try:
        expiry_at = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransferError("HIU key expiry is invalid") from exc
    if _aware(expiry_at) <= datetime.now(UTC):
        raise TransferError("HIU key material has expired")
    return key_value, nonce, expiry


async def _post_page(url: str, payload: dict[str, Any]) -> None:
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = await client.post(url, json=payload)
                if 200 <= response.status_code < 300:
                    return
                last_error = TransferError(f"HIU returned HTTP {response.status_code}")
            except httpx.HTTPError as exc:
                last_error = exc
            if attempt + 1 < _MAX_ATTEMPTS:
                await asyncio.sleep(0.25 * (2**attempt))
    raise TransferError("HIU data push failed after bounded retries") from last_error


async def _notify_gateway(
    row: AbdmHipHealthInformationRequest,
    *,
    session_status: str,
    statuses: list[dict[str, str]],
) -> None:
    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            await hip_gateway.notify_hi_transfer(
                consent_id=row.consent_artefact_id,
                transaction_id=row.transaction_id,
                session_status=session_status,
                status_responses=statuses,
            )
            return
        except Exception as exc:  # outbound client normalises gateway errors
            last_error = exc
            if attempt + 1 < _MAX_ATTEMPTS:
                await asyncio.sleep(0.25 * (2**attempt))
    raise TransferError("ABDM transfer notification failed after bounded retries") from last_error


async def transfer_transaction(transaction_id: str) -> None:
    """Complete one previously acknowledged HIP transfer transaction."""
    statuses: list[dict[str, str]] = []
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(AbdmHipHealthInformationRequest).where(
                    AbdmHipHealthInformationRequest.transaction_id == transaction_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            log.error("ABDM transfer row disappeared before worker start")
            return
        if row.status == "delivered":
            return
        try:
            push_url = await _validate_data_push_url(row.data_push_url)
            artefact = (
                await db.execute(
                    select(AbdmHipConsentArtefact).where(
                        AbdmHipConsentArtefact.facility_id == row.facility_id,
                        AbdmHipConsentArtefact.consent_artefact_id == row.consent_artefact_id,
                    )
                )
            ).scalar_one_or_none()
            if artefact is None:
                raise TransferError("Consent artefact disappeared before transfer")
            authorisation = await hip_service.authorise_hi_request(
                db,
                facility_id=row.facility_id,
                consent_artefact_id=row.consent_artefact_id,
                requested_hi_types=list(artefact.hi_types or []),
                requested_from=artefact.date_range_from,
                requested_to=artefact.date_range_to,
            )
            contexts = await hip_service.list_care_contexts_for_transfer(
                db,
                facility_id=row.facility_id,
                abha_address=artefact.abha_address,
                authorisation=authorisation,
            )
            if not contexts:
                raise TransferError("Consent covers no linked clinical care contexts")
            facility = await db.get(Facility, row.facility_id)
            if facility is None:
                raise TransferError("Facility no longer exists")
            hiu_public, hiu_nonce, key_expiry = _hiu_key_material(row)
            for page_number, context in enumerate(contexts):
                facts = await _clinical_facts(db, context, facility=facility)
                bundle = build_clinical_bundle(context.hi_type, **facts)
                ciphertext, key_material, checksum = hip_service.encrypt_bundle_for_hiu(
                    bundle,
                    hiu_public_key_b64=hiu_public,
                    hiu_nonce_b64=hiu_nonce,
                )
                key_material["dhPublicKey"]["expiry"] = key_expiry
                await _post_page(
                    push_url,
                    {
                        "pageNumber": page_number,
                        "pageCount": len(contexts),
                        "transactionId": row.transaction_id,
                        "entries": [
                            {
                                "content": ciphertext,
                                "media": _FHIR_MEDIA,
                                "checksum": checksum,
                                "careContextReference": context.reference,
                            }
                        ],
                        "keyMaterial": key_material,
                    },
                )
                statuses.append(
                    {
                        "careContextReference": context.reference,
                        "hiStatus": "OK",
                        "description": "FHIR document transferred",
                    }
                )
            row.status = "delivered"
            row.bundles_sent = str(len(statuses))
            row.failure_reason = None
            row.completed_at = datetime.now(UTC)
            await db.commit()
            try:
                await _notify_gateway(
                    row,
                    session_status="TRANSFERRED",
                    statuses=statuses,
                )
            except TransferError as exc:
                # The HIU already authenticated and accepted every page.  A
                # later gateway-notification outage must not rewrite that
                # clinical fact as "failed" or trigger a contradictory FAILED
                # notification.  Keep it delivered and leave an operational
                # reason for a notifier/reconciliation job to retry.
                row.failure_reason = str(exc)[:500]
                await db.commit()
                log.exception("ABDM data was delivered but the gateway notification failed")
        except Exception as exc:
            safe_reason = str(exc)[:500] or type(exc).__name__
            row.status = "failed"
            row.failure_reason = safe_reason
            row.completed_at = datetime.now(UTC)
            await db.commit()
            failed_statuses = statuses or [
                {
                    "careContextReference": "",
                    "hiStatus": "ERRORED",
                    "description": "Health information transfer failed",
                }
            ]
            try:
                await _notify_gateway(row, session_status="FAILED", statuses=failed_statuses)
            except TransferError:
                log.exception("ABDM transfer failed and failure notification could not be sent")
            else:
                log.error("ABDM transfer failed (%s)", type(exc).__name__)

"""Consent-bound external document store; never a local clinical-record import.

This is an authorization check, NOT a replacement for the NRCeS validator.
Profile names follow the published NRCeS Composition profiles. An unverifiable
patient identity or unsupported document is refused rather than guessed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.security import decrypt_pii
from app.integrations.abdm.hiu.models import (
    AbdmConsentRequest,
    AbdmHiuConsentArtefact,
    AbdmHiuHealthInformationRequest,
    AbdmReceivedBundle,
)
from app.patients.models import Patient

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_RESOURCES = 1000
MAX_PDF_BYTES = 1024 * 1024
PROFILE_ROOT = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/"
PROFILES = {
    "OPConsultRecord": "OPConsultation",
    "PrescriptionRecord": "Prescription",
    "DiagnosticReportRecord": "DiagnosticReport",
    "DischargeSummaryRecord": "DischargeSummary",
    "WellnessRecord": "WellnessRecord",
}
ABHA_SYSTEMS = {"https://healthid.abdm.gov.in", "https://healthid.ndhm.gov.in"}


class RecordRefused(ValueError):
    """Redacted refusal safe to persist and expose to an authorized caller."""


def _validate_pdf(value: dict) -> None:
    encoded = value.get("data")
    if value.get("contentType") != "application/pdf" or not isinstance(encoded, str):
        raise RecordRefused("Only embedded PDF attachments are supported")
    if len(encoded) > 4 * ((MAX_PDF_BYTES + 2) // 3):
        raise RecordRefused("The PDF attachment exceeds the size limit")
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise RecordRefused("The PDF attachment is not valid base64") from exc
    if not data.startswith(b"%PDF-") or not 0 < len(data) <= MAX_PDF_BYTES:
        raise RecordRefused("The attachment does not contain a bounded PDF")
    if "size" in value and value["size"] != len(data):
        raise RecordRefused("The PDF attachment size does not match")
    if "hash" in value:
        # FHIR Attachment.hash is SHA-1, not a replacement for authenticated
        # transport or the SHA-256 digest of the entire received document.
        digest = base64.b64encode(hashlib.sha1(data, usedforsecurity=False).digest()).decode()
        if value["hash"] != digest:
            raise RecordRefused("The PDF attachment hash does not match")


def _reachable_resources(composition: dict, refs: dict) -> set[int]:
    """Local reference traversal only. No URLs are fetched, ever."""
    stack, seen = [composition], set()
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if id(node) in seen:
                continue
            seen.add(id(node))
            for key, value in node.items():
                if key in {"reference", "url"} and isinstance(value, str) and value in refs:
                    stack.append(refs[value])
                stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    return seen


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def record_aad(row: AbdmReceivedBundle) -> bytes:
    return f"abdm:received:{row.facility_id}:{row.hi_request_id}:{row.id}".encode()


def wire_digest(
    *,
    content: str,
    public_key: str,
    nonce: str,
    reference: str | None,
    media: str,
    checksum: str | None,
) -> str:
    """Fingerprint exactly what authenticated a page, not a sender's checksum alone."""
    encoded = json.dumps(
        [content, public_key, nonce, reference, media, checksum],
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Grant:
    artefact: AbdmHiuConsentArtefact
    request: AbdmConsentRequest
    patient: Patient
    detail: dict
    hip_id: str


async def grant_for(
    db: AsyncSession, request: AbdmHiuHealthInformationRequest, *, now: datetime
) -> Grant:
    artefact = await db.get(AbdmHiuConsentArtefact, request.artefact_id)
    if (
        artefact is None
        or artefact.facility_id != request.facility_id
        or artefact.status != "granted"
        or artefact.expires_at is None
        or aware(artefact.expires_at) <= now
    ):
        raise RecordRefused("Consent is no longer usable")
    consent = await db.get(AbdmConsentRequest, artefact.consent_request_id)
    patient = await db.get(Patient, consent.patient_id) if consent and consent.patient_id else None
    if (
        consent is None
        or consent.facility_id != request.facility_id
        or consent.status in {"revoked", "expired", "denied", "failed"}
        or patient is None
        or patient.facility_id != request.facility_id
        or patient.deleted_at is not None
        or patient.merged_into_patient_id is not None
        or patient.abha_linked_at is None
        or patient.abha_address != consent.abha_address
    ):
        raise RecordRefused("A verified local patient binding is required")
    raw = artefact.raw_artefact
    detail = raw.get("consentDetail") if isinstance(raw, dict) else None
    if not isinstance(detail, dict):
        raise RecordRefused("The complete consent artefact is required")
    identity, hip = detail.get("patient"), detail.get("hip")
    if (
        not isinstance(identity, dict)
        or identity.get("id") != consent.abha_address
        or not isinstance(hip, dict)
        or not isinstance(hip.get("id"), str)
        or not hip["id"].strip()
    ):
        raise RecordRefused("Consent patient or source HIP cannot be verified")
    return Grant(artefact, consent, patient, detail, hip["id"])


def validate_document(bundle: dict, grant: Grant, reference: str | None) -> tuple[str, datetime]:
    """Bind context, Composition type/date and every patient subject to the grant."""
    contexts = grant.detail.get("careContexts")
    if (
        not reference
        or not isinstance(contexts, list)
        or not any(
            isinstance(c, dict) and c.get("careContextReference") == reference for c in contexts
        )
    ):
        raise RecordRefused("The received care context was not consented")
    entries = bundle.get("entry")
    if (
        bundle.get("resourceType") != "Bundle"
        or bundle.get("type") != "document"
        or not isinstance(entries, list)
        or not 1 <= len(entries) <= MAX_RESOURCES
    ):
        raise RecordRefused("A bounded FHIR document Bundle is required")
    resources, refs = [], {}
    for entry in entries:
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if not isinstance(resource, dict):
            raise RecordRefused("Every bundle entry must contain a resource")
        resources.append(resource)
        for key in (
            entry.get("fullUrl"),
            f"{resource.get('resourceType')}/{resource.get('id')}" if resource.get("id") else None,
        ):
            if key:
                if not isinstance(key, str) or (key in refs and refs[key] is not resource):
                    raise RecordRefused("Ambiguous resource references are not accepted")
                refs[key] = resource
    composition = resources[0]
    if (
        composition.get("resourceType") != "Composition"
        or composition.get("status") not in {"final", "amended"}
        or sum(r.get("resourceType") == "Composition" for r in resources) != 1
    ):
        raise RecordRefused("One finalized Composition must lead the document")
    meta = composition.get("meta")
    profiles = meta.get("profile", []) if isinstance(meta, dict) else []
    if not isinstance(profiles, list):
        raise RecordRefused("Document profile cannot be verified")
    types = {
        hi_type
        for profile, hi_type in PROFILES.items()
        for declared in profiles
        if isinstance(declared, str) and declared.split("|")[0] == PROFILE_ROOT + profile
    }
    if len(types) != 1 or not types.issubset(set(grant.artefact.hi_types or [])):
        raise RecordRefused("The document type was not consented or is unsupported")
    try:
        date = datetime.fromisoformat(composition["date"].replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("timezone required")
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise RecordRefused("The document date must include a timezone") from exc
    start, end = grant.artefact.date_range_from, grant.artefact.date_range_to
    if start is None or end is None or not aware(start) <= date <= aware(end):
        raise RecordRefused("The document is outside the consented date range")

    patients = [r for r in resources if r.get("resourceType") == "Patient"]
    if len(patients) != 1:
        raise RecordRefused("A single identifiable patient is required")
    patient = patients[0]
    identifiers = patient.get("identifier", [])
    expected = (grant.patient.abha_number or "").replace("-", "")
    if not isinstance(identifiers, list) or not any(
        isinstance(i, dict)
        and i.get("system") in ABHA_SYSTEMS
        and isinstance(i.get("value"), str)
        and (
            i["value"] == grant.request.abha_address
            or (
                len(expected) == 14
                and expected.isdigit()
                and i["value"].replace("-", "") == expected
            )
        )
        for i in identifiers
    ):
        raise RecordRefused("The document patient does not match the verified ABHA")

    def is_patient_reference(value: object) -> bool:
        return (
            isinstance(value, dict)
            and isinstance(value.get("reference"), str)
            and refs.get(value["reference"]) is patient
        )

    subject = composition.get("subject")
    if not is_patient_reference(subject):
        raise RecordRefused("The Composition patient reference cannot be verified")
    # Walk nested patient/subject references too. Do not resolve network URLs,
    # contained patients or a second subject by guessing which patient is meant.
    reachable = _reachable_resources(composition, refs)
    for resource in resources:
        if resource.get("resourceType") in {"Binary", "DocumentReference"} and id(resource) not in reachable:
            raise RecordRefused("An attachment is not referenced by the consented document")
        if resource.get("resourceType") == "Binary":
            _validate_pdf(resource)
            security = resource.get("securityContext")
            if security is not None and not is_patient_reference(security):
                target = refs.get(security.get("reference")) if isinstance(security, dict) else None
                if not isinstance(target, dict) or not is_patient_reference(target.get("subject")):
                    raise RecordRefused("The attachment security context cannot be verified")
    stack = list(resources)
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            if node.get("resourceType") == "Bundle" or node.get("contained"):
                raise RecordRefused(
                    "Nested bundles, opaque resources and contained records are unsupported"
                )
            if "contentType" in node and "data" in node:
                if id(node) not in reachable:
                    raise RecordRefused("An attachment is not referenced by the consented document")
                _validate_pdf(node)
            for name, value in node.items():
                if name in {"subject", "patient"}:
                    if not is_patient_reference(value):
                        raise RecordRefused(
                            "A clinical subject does not match the consented patient"
                        )
                stack.append(value)
    return types.pop(), date


async def read_record(
    db: AsyncSession,
    record_id: uuid.UUID,
    *,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
    now: datetime | None = None,
) -> dict:
    row = (
        await db.execute(
            select(AbdmReceivedBundle).where(
                AbdmReceivedBundle.id == record_id,
                AbdmReceivedBundle.facility_id == facility_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise RecordRefused("External record is unavailable")
    request = await db.get(AbdmHiuHealthInformationRequest, row.hi_request_id)
    grant = await grant_for(db, request, now=now or datetime.now(UTC))
    # Conservative initial boundary: only the clinician who requested consent.
    # Extending this to care teams requires an explicit clinical access policy.
    if (
        grant.request.created_by != actor_id
        or row.status != "stored"
        or row.content_encrypted is None
        or row.erased_at is not None
    ):
        raise RecordRefused("External record is unavailable")
    value = decrypt_pii(bytes(row.content_encrypted), associated_data=record_aad(row))
    if hashlib.sha256(value.encode()).hexdigest() != row.content_sha256:
        raise RecordRefused("External record integrity check failed")
    bundle = json.loads(value)
    validate_document(bundle, grant, row.care_context_reference)
    return bundle


async def erase_unusable_content(db: AsyncSession, *, now: datetime) -> int:
    """Clear consent-cache bytes after revoke/dataEraseAt, retaining receipt facts.

    This does not touch locally authored clinical records, historical outbox
    copies or backups. Those need their own reviewed retention/recovery policy.
    """
    from sqlalchemy import or_

    rows = (
        (
            await db.execute(
                select(AbdmReceivedBundle)
                .join(
                    AbdmHiuHealthInformationRequest,
                    AbdmHiuHealthInformationRequest.id == AbdmReceivedBundle.hi_request_id,
                )
                .join(
                    AbdmHiuConsentArtefact,
                    AbdmHiuConsentArtefact.id == AbdmHiuHealthInformationRequest.artefact_id,
                )
                .where(
                    AbdmReceivedBundle.content_encrypted.is_not(None),
                    or_(
                        AbdmHiuConsentArtefact.status != "granted",
                        AbdmHiuConsentArtefact.expires_at.is_(None),
                        AbdmHiuConsentArtefact.expires_at <= now,
                    ),
                )
                .with_for_update(of=AbdmReceivedBundle, skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.content_encrypted = None
        row.content_key_version = None
        row.erased_at = now
    await db.flush()
    return len(rows)

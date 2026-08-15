"""FHIR R4 bundle builder skeleton (B1-W3-01).

Produces valid-shape R4 `Bundle` resources (type=document) for the five ABDM
record types the HIP must share. These are STRUCTURAL STUBS: correct resourceType,
Composition + section skeleton, subject/author references — real clinical content is
filled by the owning module (encounters/lab/pharmacy/ipd) in Phase 2. Raw bundles are
persisted to Mongo (fhir_bundles) and audited via fhir_bundle_transactions (0026).

Every builder returns a dict ready to json-dump; `validate_min()` checks the invariants
ABDM's gateway rejects on.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

RECORD_TYPES = (
    "OPConsultation",
    "DiagnosticReport",
    "Prescription",
    "DischargeSummary",
    "WellnessRecord",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ref(resource_type: str, rid: str) -> dict:
    return {"reference": f"{resource_type}/{rid}"}


def _composition(record_type: str, patient_id: str, author_hpr_id: str) -> dict:
    return {
        "resourceType": "Composition",
        "id": str(uuid.uuid4()),
        "status": "final",
        "type": {"text": record_type},
        "subject": _ref("Patient", patient_id),
        "date": _now(),
        "author": [{"display": f"HPR:{author_hpr_id}"}],
        "title": record_type,
        "section": [{"title": record_type, "entry": []}],
    }


def build_bundle(record_type: str, *, patient_id: str, author_hpr_id: str,
                 care_context_id: str | None = None) -> dict:
    """Build a document Bundle skeleton for one ABDM record type."""
    if record_type not in RECORD_TYPES:
        raise ValueError(f"Unknown ABDM record type: {record_type!r}")
    comp = _composition(record_type, patient_id, author_hpr_id)
    return {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "document",
        "timestamp": _now(),
        "meta": {"profile": [
            "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle"]},
        "identifier": {"system": "urn:ietf:rfc:3986", "value": f"urn:uuid:{uuid.uuid4()}"},
        "entry": [
            {"fullUrl": f"Composition/{comp['id']}", "resource": comp},
            {"fullUrl": f"Patient/{patient_id}",
             "resource": {"resourceType": "Patient", "id": patient_id}},
        ],
        # non-FHIR side-channel our sync layer reads (stripped before transmit):
        "_healthdoc": {"care_context_id": care_context_id, "record_type": record_type},
    }


def build_all(patient_id: str, author_hpr_id: str) -> dict[str, dict]:
    """One stub bundle per record type — used by tests and the W3 smoke check."""
    return {rt: build_bundle(rt, patient_id=patient_id, author_hpr_id=author_hpr_id)
            for rt in RECORD_TYPES}


def validate_min(bundle: dict) -> list[str]:
    """Return a list of problems; empty list == passes ABDM's minimum shape checks."""
    errs: list[str] = []
    if bundle.get("resourceType") != "Bundle":
        errs.append("resourceType must be 'Bundle'")
    if bundle.get("type") != "document":
        errs.append("Bundle.type must be 'document'")
    entries = bundle.get("entry", [])
    first_resource = entries[0].get("resource", {}) if entries else {}
    if first_resource.get("resourceType") != "Composition":
        errs.append("first entry must be a Composition")
    if not any(e.get("resource", {}).get("resourceType") == "Patient" for e in entries):
        errs.append("bundle must contain a Patient")
    return errs

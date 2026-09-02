"""NRCeS/ABDM FHIR R4 document bundle construction.

The public transfer worker calls :func:`build_clinical_bundle` with facts read
from HealthDoc's clinical tables. The builder never queries the database and
never fills a missing clinical field with demo text. This separation makes the
wire document straightforward to test and prevents a transport retry from
changing what was selected.

The profiles, SNOMED document codes and identifier systems below mirror NHA's
official ABDM wrapper/FHIR mapper. This is deliberately a small, auditable
mapper for the record types HealthDoc can substantiate from its own schema,
rather than a generic generator that silently invents data.
"""

from __future__ import annotations

import base64
import html
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

DOCUMENT_BUNDLE_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle"
PROFILE_ROOT = "https://nrces.in/ndhm/fhir/r4/StructureDefinition"
SNOMED = "http://snomed.info/sct"
IDENTIFIER_TYPE = "http://terminology.hl7.org/CodeSystem/v2-0203"

RECORD_TYPES = (
    "OPConsultation",
    "DiagnosticReport",
    "Prescription",
    "DischargeSummary",
    "WellnessRecord",
)

_DOCUMENTS: dict[str, tuple[str, str | None, str]] = {
    "OPConsultation": ("OPConsultRecord", "371530004", "Clinical consultation report"),
    "DiagnosticReport": ("DiagnosticReportRecord", "721981007", "Diagnostic studies report"),
    "Prescription": ("PrescriptionRecord", "440545006", "Prescription record"),
    "DischargeSummary": ("DischargeSummaryRecord", "373942005", "Discharge summary"),
    # WellnessRecord fixes Composition.type.text to this label; unlike the
    # other four document profiles it does not fix a SNOMED document code.
    "WellnessRecord": ("WellnessRecord", None, "Wellness Record"),
}

_SECTION_CODES = {
    "chief_complaints": ("422843007", "Chief complaint section"),
    "diagnoses": ("371529009", "History and physical report"),
    "observations": ("425044008", "Physical exam section"),
    "allergies": ("722446000", "Allergy record"),
    "medications": ("721912009", "Medication summary document"),
    "prescription": ("440545006", "Prescription record"),
    "diagnostic_reports": ("721981007", "Diagnostic studies report"),
    "care_plan": ("734163000", "Care plan"),
}


def _iso(value: datetime | date | None = None) -> str:
    value = value or datetime.now(UTC)
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return _iso(value)
    return value


def _rid(kind: str, source: Any) -> str:
    """Create a stable, FHIR-safe id without leaking a business identifier."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"healthdoc:fhir:{kind}:{source}"))


def _meta(profile: str, updated: datetime | None = None) -> dict[str, Any]:
    return {
        "versionId": "1",
        "lastUpdated": _iso(updated),
        "profile": [f"{PROFILE_ROOT}/{profile}"],
    }


def _narrative(value: str) -> dict[str, str]:
    """Return the minimal generated XHTML narrative required by FHIR dom-6."""
    return {
        "status": "generated",
        "div": ('<div xmlns="http://www.w3.org/1999/xhtml">' f"{html.escape(value)}</div>"),
    }


def _reference(resource: Mapping[str, Any], display: str | None = None) -> dict[str, str]:
    # A document Bundle is a self-contained graph.  NRCeS examples use UUID
    # URNs for both entry.fullUrl and every internal reference; relative
    # Resource/id references are not absolute and the official validator
    # cannot resolve them to the matching profile slice.
    ref = {
        "reference": f"urn:uuid:{resource['id']}",
        "type": str(resource["resourceType"]),
    }
    if display:
        ref["display"] = display
    return ref


def _patient(data: Mapping[str, Any], authored_at: datetime) -> dict[str, Any]:
    source_id = data.get("id")
    if not source_id or not data.get("name") or not data.get("identifier"):
        raise ValueError("FHIR patient requires id, name and identifier")
    identifiers = [
        {
            "type": {
                "coding": [
                    {"system": IDENTIFIER_TYPE, "code": "MR", "display": "Medical record number"}
                ]
            },
            "system": "https://healthid.abdm.gov.in",
            "value": str(data["identifier"]),
        }
    ]
    if data.get("abha_number"):
        identifiers.append(
            {
                "system": "https://healthid.abdm.gov.in",
                "value": str(data["abha_number"]),
            }
        )
    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": _rid("patient", source_id),
        "meta": _meta("Patient", authored_at),
        "text": _narrative(f"Patient: {data['name']}"),
        "identifier": identifiers,
        "name": [{"text": str(data["name"])}],
    }
    gender = str(data.get("gender") or "").lower()
    resource["gender"] = gender if gender in {"male", "female", "other", "unknown"} else "unknown"
    if data.get("birth_date"):
        resource["birthDate"] = _iso(data["birth_date"])
    if data.get("mobile"):
        resource["telecom"] = [{"system": "phone", "value": str(data["mobile"]), "use": "mobile"}]
    return resource


def _practitioner(data: Mapping[str, Any], authored_at: datetime) -> dict[str, Any]:
    if not data.get("id") or not data.get("name") or not data.get("registration_number"):
        raise ValueError("FHIR practitioner requires id, name and registration_number")
    return {
        "resourceType": "Practitioner",
        "id": _rid("practitioner", data["id"]),
        "meta": _meta("Practitioner", authored_at),
        "text": _narrative(f"Practitioner: {data['name']}"),
        "identifier": [
            {
                "type": {
                    "coding": [
                        {
                            "system": IDENTIFIER_TYPE,
                            "code": "MD",
                            "display": "Medical License number",
                        }
                    ]
                },
                "system": "https://doctor.abdm.gov.in",
                "value": str(data["registration_number"]),
            }
        ],
        "name": [{"text": str(data["name"])}],
    }


def _organization(data: Mapping[str, Any], authored_at: datetime) -> dict[str, Any]:
    if not data.get("id") or not data.get("name") or not data.get("hfr_id"):
        raise ValueError("FHIR organization requires id, name and HFR id")
    return {
        "resourceType": "Organization",
        "id": _rid("organization", data["id"]),
        "meta": _meta("Organization", authored_at),
        "text": _narrative(f"Facility: {data['name']}"),
        "identifier": [
            {
                "type": {
                    "coding": [
                        {"system": IDENTIFIER_TYPE, "code": "PRN", "display": "Provider number"}
                    ]
                },
                "system": "https://facility.abdm.gov.in",
                "value": str(data["hfr_id"]),
            }
        ],
        "name": str(data["name"]),
    }


def _encounter(
    data: Mapping[str, Any], patient: Mapping[str, Any], authored_at: datetime
) -> dict[str, Any]:
    if not data.get("id"):
        raise ValueError("FHIR encounter requires id")
    status = str(data.get("status") or "").lower()
    fhir_status = {
        "registered": "planned",
        "in_consultation": "in-progress",
        "admitted": "in-progress",
        "completed": "finished",
        "closed": "finished",
        "discharged": "finished",
        "cancelled": "cancelled",
        "lwbs": "cancelled",
    }.get(status, "unknown")
    inpatient = str(data.get("class") or "").upper() in {"IMP", "IPD", "INPATIENT"}
    resource: dict[str, Any] = {
        "resourceType": "Encounter",
        "id": _rid("encounter", data["id"]),
        "meta": _meta("Encounter", authored_at),
        "text": _narrative("Clinical encounter"),
        "status": fhir_status,
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "IMP" if inpatient else "AMB",
            "display": "inpatient encounter" if inpatient else "ambulatory",
        },
        "subject": _reference(patient, str(data.get("patient_name") or "")),
    }
    start, end = data.get("start"), data.get("end")
    if start or end:
        resource["period"] = {
            key: _iso(value) for key, value in (("start", start), ("end", end)) if value
        }
    return resource


def _condition(item: Mapping[str, Any], patient: Mapping[str, Any], index: int) -> dict[str, Any]:
    text = item.get("text")
    if not text:
        raise ValueError("FHIR condition requires text")
    coding: list[dict[str, str]] = []
    if item.get("code"):
        coding.append(
            {
                "system": str(item.get("system") or "http://hl7.org/fhir/sid/icd-10"),
                "code": str(item["code"]),
                "display": str(text),
            }
        )
    code: dict[str, Any] = {"text": str(text)}
    if coding:
        code["coding"] = coding
    return {
        "resourceType": "Condition",
        "id": _rid("condition", item.get("id") or f"{patient['id']}:{index}:{text}"),
        "meta": _meta("Condition"),
        "text": _narrative(f"Condition: {text}"),
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                }
            ]
        },
        "code": code,
        "subject": _reference(patient),
    }


def _allergy(item: Mapping[str, Any], patient: Mapping[str, Any], index: int) -> dict[str, Any]:
    text = item.get("substance")
    if not text:
        raise ValueError("FHIR allergy requires substance")
    resource: dict[str, Any] = {
        "resourceType": "AllergyIntolerance",
        "id": _rid("allergy", item.get("id") or f"{patient['id']}:{index}:{text}"),
        "meta": _meta("AllergyIntolerance"),
        "text": _narrative(f"Allergy: {text}"),
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                    "code": "active" if item.get("status", "active") == "active" else "inactive",
                }
            ]
        },
        "code": {"text": str(text)},
        "patient": _reference(patient),
    }
    if item.get("reaction"):
        resource["reaction"] = [{"manifestation": [{"text": str(item["reaction"])}]}]
    return resource


def _observation(
    item: Mapping[str, Any],
    patient: Mapping[str, Any],
    practitioner: Mapping[str, Any],
    authored_at: datetime,
    index: int,
) -> dict[str, Any]:
    name = item.get("name")
    if not name or item.get("value") is None:
        raise ValueError("FHIR observation requires name and value")
    value = _json_value(item["value"])
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "id": _rid("observation", item.get("id") or f"{patient['id']}:{index}:{name}"),
        "meta": _meta("Observation"),
        "text": _narrative(f"{name}: {value}{' ' + str(item['unit']) if item.get('unit') else ''}"),
        "status": "final",
        "code": {"text": str(name)},
        "subject": _reference(patient),
        "effectiveDateTime": _iso(item.get("effective") or authored_at),
        "performer": [_reference(practitioner)],
    }
    if isinstance(value, int | float) and not isinstance(value, bool):
        resource["valueQuantity"] = {"value": value}
        if item.get("unit"):
            resource["valueQuantity"]["unit"] = str(item["unit"])
    elif isinstance(value, bool):
        resource["valueBoolean"] = value
    else:
        resource["valueString"] = str(value)
    return resource


def _medication(
    item: Mapping[str, Any],
    patient: Mapping[str, Any],
    practitioner: Mapping[str, Any],
    authored_at: datetime,
    index: int,
) -> dict[str, Any]:
    if not item.get("name"):
        raise ValueError("FHIR medication request requires medicine name")
    resource: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": _rid("medication", item.get("id") or f"{patient['id']}:{index}:{item['name']}"),
        "meta": _meta("MedicationRequest"),
        "text": _narrative(f"Medication request: {item['name']}"),
        "status": "active",
        "intent": "order",
        # HealthDoc stores the prescribed product name but not a SNOMED drug
        # concept.  Use the truthful generic Medicinal product concept and
        # retain the clinician-entered product in text; do not guess a more
        # specific ingredient code from a free-text brand name.
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": SNOMED,
                    "code": "763158003",
                    "display": "Medicinal product",
                }
            ],
            "text": str(item["name"]),
        },
        "subject": _reference(patient),
        "authoredOn": _iso(authored_at),
        "requester": _reference(practitioner),
        "substitution": {"allowedBoolean": False},
    }
    dosage: dict[str, Any] = {}
    instructions = [
        str(value)
        for value in (item.get("dosage"), item.get("frequency"), item.get("instructions"))
        if value
    ]
    if instructions:
        dosage["text"] = "; ".join(instructions)
    if item.get("route"):
        dosage["route"] = {"text": str(item["route"])}
    if not dosage:
        raise ValueError("FHIR medication request requires dosage instructions")
    resource["dosageInstruction"] = [dosage]
    return resource


def _diagnostic_report(
    item: Mapping[str, Any],
    patient: Mapping[str, Any],
    encounter: Mapping[str, Any],
    practitioner: Mapping[str, Any],
    authored_at: datetime,
    index: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if not item.get("name"):
        raise ValueError("FHIR diagnostic report requires a test name")
    observations = [
        _observation(value, patient, practitioner, authored_at, pos)
        for pos, value in enumerate(item.get("observations") or [])
    ]
    is_lab = item.get("kind") == "lab"
    profile = "DiagnosticReportLab" if is_lab else "DiagnosticReportImaging"
    code = ("11502-2", "Laboratory report") if is_lab else ("18748-4", "Diagnostic imaging study")
    category = ("108252007", "Laboratory procedure") if is_lab else ("363679005", "Imaging")
    report: dict[str, Any] = {
        "resourceType": "DiagnosticReport",
        "id": _rid(
            "diagnostic-report",
            item.get("id") or f"{patient['id']}:{index}:{item['name']}",
        ),
        "meta": _meta(profile),
        "text": _narrative(f"Diagnostic report: {item['name']}"),
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": SNOMED,
                        "code": category[0],
                        "display": category[1],
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": code[0],
                    "display": code[1],
                }
            ],
            "text": str(item["name"]),
        },
        "subject": _reference(patient),
        "encounter": _reference(encounter),
        "resultsInterpreter": [_reference(practitioner)],
    }
    if observations:
        report["result"] = [_reference(value) for value in observations]
    report["issued"] = _iso(item.get("issued") or authored_at)
    conclusion = str(item.get("conclusion") or "").strip()
    if is_lab and not conclusion:
        conclusion = "; ".join(
            (
                f"{value.get('name')}: {value.get('value')}"
                f"{' ' + str(value['unit']) if value.get('unit') else ''}"
            )
            for value in (item.get("observations") or [])
        )
    if conclusion:
        report["conclusion"] = conclusion
    attachments: list[dict[str, Any]] = []
    if is_lab:
        if not observations:
            raise ValueError("FHIR laboratory report requires structured observations")
    else:
        pacs_study_uid = str(item.get("pacs_study_uid") or "").strip()
        modality = str(item.get("modality") or "").strip()
        if not pacs_study_uid or not conclusion or not modality:
            raise ValueError(
                "FHIR imaging report requires modality, PACS study UID and signed findings"
            )
        # HealthDoc stores a PACS study UID, not the source DICOM bytes.  The
        # attachment therefore carries an explicit PACS-reference document;
        # it never labels a UID string as application/dicom or invents image
        # pixels.  The HIU can use the UID to retrieve the study through the
        # separately governed PACS channel.
        pacs_reference = json.dumps(
            {
                "pacsStudyUid": pacs_study_uid,
                "modality": modality,
                "report": conclusion,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        media = {
            "resourceType": "Media",
            "id": _rid("media", item.get("id") or pacs_study_uid),
            "meta": _meta("Media", authored_at),
            "text": _narrative(f"PACS study reference: {pacs_study_uid}"),
            "status": "completed",
            "modality": {
                "coding": [
                    {
                        "system": SNOMED,
                        "code": "363679005",
                        "display": "Imaging",
                    }
                ],
                "text": modality,
            },
            "subject": _reference(patient),
            "createdDateTime": _iso(item.get("issued") or authored_at),
            "content": {
                "contentType": "application/json",
                "data": base64.b64encode(pacs_reference).decode(),
                "title": f"PACS study reference for {item['name']}",
                "creation": _iso(item.get("issued") or authored_at),
            },
        }
        attachments.append(media)
        report["media"] = [{"link": _reference(media, "PACS study reference")}]
    return report, observations, attachments


def _section(
    key: str,
    resources: Sequence[Mapping[str, Any]],
    *,
    text: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    code, display = _SECTION_CODES[key]
    section: dict[str, Any] = {
        "title": title or display,
        "code": {"coding": [{"system": SNOMED, "code": code, "display": display}]},
    }
    if resources:
        section["entry"] = [_reference(resource) for resource in resources]
    if text:
        section["text"] = {
            "status": "generated",
            "div": ('<div xmlns="http://www.w3.org/1999/xhtml">' f"{html.escape(text)}</div>"),
        }
    return section


def build_clinical_bundle(
    record_type: str,
    *,
    patient: Mapping[str, Any],
    practitioner: Mapping[str, Any],
    organization: Mapping[str, Any],
    encounter: Mapping[str, Any],
    authored_at: datetime,
    care_context_reference: str,
    chief_complaints: Sequence[Mapping[str, Any]] = (),
    diagnoses: Sequence[Mapping[str, Any]] = (),
    allergies: Sequence[Mapping[str, Any]] = (),
    observations: Sequence[Mapping[str, Any]] = (),
    medications: Sequence[Mapping[str, Any]] = (),
    diagnostic_reports: Sequence[Mapping[str, Any]] = (),
    care_plan: str | None = None,
) -> dict[str, Any]:
    """Build one transfer-ready FHIR document from explicit clinical facts."""
    if record_type not in _DOCUMENTS:
        raise ValueError(f"Unknown ABDM record type: {record_type!r}")
    profile, document_code, document_title = _DOCUMENTS[record_type]
    patient_resource = _patient(patient, authored_at)
    practitioner_resource = _practitioner(practitioner, authored_at)
    organization_resource = _organization(organization, authored_at)
    encounter_resource = _encounter(encounter, patient_resource, authored_at)

    complaints = [
        _condition(item, patient_resource, pos) for pos, item in enumerate(chief_complaints)
    ]
    conditions = [_condition(item, patient_resource, pos) for pos, item in enumerate(diagnoses)]
    allergy_resources = [
        _allergy(item, patient_resource, pos) for pos, item in enumerate(allergies)
    ]
    observation_resources = [
        _observation(
            item,
            patient_resource,
            practitioner_resource,
            authored_at,
            pos,
        )
        for pos, item in enumerate(observations)
    ]
    medication_resources = [
        _medication(
            item,
            patient_resource,
            practitioner_resource,
            authored_at,
            pos,
        )
        for pos, item in enumerate(medications)
    ]
    report_resources: list[dict[str, Any]] = []
    report_observations: list[dict[str, Any]] = []
    report_attachments: list[dict[str, Any]] = []
    for pos, item in enumerate(diagnostic_reports):
        report, result_observations, attachments = _diagnostic_report(
            item,
            patient_resource,
            encounter_resource,
            practitioner_resource,
            authored_at,
            pos,
        )
        report_resources.append(report)
        report_observations.extend(result_observations)
        report_attachments.extend(attachments)

    sections: list[dict[str, Any]] = []
    candidates = (
        ("chief_complaints", complaints),
        ("diagnoses", conditions),
        ("observations", observation_resources),
        ("allergies", allergy_resources),
        ("medications", medication_resources),
        ("diagnostic_reports", report_resources),
    )
    for key, resources in candidates:
        if resources:
            section_key = (
                "prescription" if record_type == "Prescription" and key == "medications" else key
            )
            section_title = (
                "Other Observations"
                if record_type == "WellnessRecord" and key == "observations"
                else None
            )
            sections.append(_section(section_key, resources, title=section_title))
    if care_plan:
        sections.append(_section("care_plan", (), text=care_plan))
    if not sections:
        raise ValueError(f"{record_type} has no clinical content to transfer")

    composition_type: dict[str, Any] = {"text": document_title}
    if document_code:
        composition_type["coding"] = [
            {
                "system": SNOMED,
                "code": document_code,
                "display": document_title,
            }
        ]
    composition = {
        "resourceType": "Composition",
        "id": str(uuid.uuid4()),
        "meta": _meta(profile, authored_at),
        "text": _narrative(document_title),
        "identifier": {
            "system": "https://healthdoc.world/fhir/document",
            "value": str(uuid.uuid4()),
        },
        "status": "final",
        "type": composition_type,
        "subject": _reference(patient_resource, str(patient["name"])),
        "encounter": _reference(encounter_resource),
        "date": _iso(authored_at),
        "author": [_reference(practitioner_resource, str(practitioner["name"]))],
        "title": document_title,
        "custodian": _reference(organization_resource, str(organization["name"])),
        "section": sections,
    }
    resources = [
        composition,
        practitioner_resource,
        organization_resource,
        patient_resource,
        encounter_resource,
        *complaints,
        *conditions,
        *observation_resources,
        *allergy_resources,
        *medication_resources,
        *report_observations,
        *report_resources,
        *report_attachments,
    ]
    bundle = {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "meta": {
            "versionId": "1",
            "lastUpdated": _iso(authored_at),
            "profile": [DOCUMENT_BUNDLE_PROFILE],
            "security": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-Confidentiality",
                    "code": "V",
                    "display": "very restricted",
                }
            ],
        },
        "identifier": {
            "system": "https://healthdoc.world/fhir/bundle",
            "value": f"{care_context_reference}:{uuid.uuid4()}",
        },
        "type": "document",
        "timestamp": _iso(authored_at),
        "entry": [
            {
                "fullUrl": f"urn:uuid:{resource['id']}",
                "resource": resource,
            }
            for resource in resources
        ],
    }
    problems = validate_min(bundle)
    if problems:
        raise ValueError("Invalid FHIR document: " + "; ".join(problems))
    return bundle


def build_bundle(
    record_type: str,
    *,
    patient_id: str,
    author_hpr_id: str,
    care_context_id: str | None = None,
) -> dict[str, Any]:
    """Compatibility helper for shape tests; production uses the fact mapper."""
    now = datetime.now(UTC)
    return build_clinical_bundle(
        record_type,
        patient={
            "id": patient_id,
            "name": patient_id,
            "identifier": patient_id,
            "gender": "unknown",
        },
        practitioner={
            "id": author_hpr_id,
            "name": author_hpr_id,
            "registration_number": author_hpr_id,
        },
        organization={
            "id": "healthdoc",
            "name": "HealthDoc",
            "hfr_id": "test-only",
        },
        encounter={"id": care_context_id or "shape-test", "status": "closed"},
        authored_at=now,
        care_context_reference=care_context_id or "shape-test",
        care_plan="FHIR bundle shape test",
    )


def build_all(patient_id: str, author_hpr_id: str) -> dict[str, dict[str, Any]]:
    return {
        record_type: build_bundle(
            record_type,
            patient_id=patient_id,
            author_hpr_id=author_hpr_id,
        )
        for record_type in RECORD_TYPES
    }


def validate_min(bundle: Mapping[str, Any]) -> list[str]:
    """Validate the non-negotiable ABDM document invariants."""
    errors: list[str] = []
    if bundle.get("resourceType") != "Bundle":
        errors.append("resourceType must be 'Bundle'")
    if bundle.get("type") != "document":
        errors.append("Bundle.type must be 'document'")
    profiles = (bundle.get("meta") or {}).get("profile") or []
    if DOCUMENT_BUNDLE_PROFILE not in profiles:
        errors.append("Bundle must declare the NRCeS DocumentBundle profile")
    entries = bundle.get("entry") or []
    first = entries[0].get("resource", {}) if entries else {}
    if first.get("resourceType") != "Composition":
        errors.append("first entry must be a Composition")
    if not first.get("section"):
        errors.append("Composition must contain clinical sections")
    for required in ("Patient", "Practitioner", "Organization", "Encounter"):
        if not any(entry.get("resource", {}).get("resourceType") == required for entry in entries):
            errors.append(f"bundle must contain a {required}")
    return errors

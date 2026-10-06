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
    "ImmunizationRecord",
    "Invoice",
)

_DOCUMENTS: dict[str, tuple[str, str | None, str]] = {
    "OPConsultation": ("OPConsultRecord", "371530004", "Clinical consultation report"),
    "DiagnosticReport": ("DiagnosticReportRecord", "721981007", "Diagnostic studies report"),
    "Prescription": ("PrescriptionRecord", "440545006", "Prescription record"),
    "DischargeSummary": ("DischargeSummaryRecord", "373942005", "Discharge summary"),
    # WellnessRecord fixes Composition.type.text to this label; unlike the
    # other four document profiles it does not fix a SNOMED document code.
    "WellnessRecord": ("WellnessRecord", None, "Wellness Record"),
    "ImmunizationRecord": ("ImmunizationRecord", "41000179103", "Immunization record"),
    # InvoiceRecord, like WellnessRecord, fixes only Composition.type.text.
    "Invoice": ("InvoiceRecord", None, "Invoice Record"),
}

#: Every other document is written within a consultation, admission or order.
#: A vaccine dose is recorded on its own, and a visit's bill may have no
#: consultation; these two profiles leave Composition.encounter optional.
_ENCOUNTER_OPTIONAL = frozenset({"ImmunizationRecord", "InvoiceRecord"})

BILLING_CODES = "https://nrces.in/ndhm/fhir/r4/CodeSystem/ndhm-billing-codes"
PRICE_COMPONENTS = "https://nrces.in/ndhm/fhir/r4/CodeSystem/ndhm-price-components"
#: ndhm-billing-codes (ndhm.in 6.5.0). An invoice is typed by its visit
#: (ndhm-invoice-types allows 00 to 03 and 99), a line by what it charges for.
_BILLING = {
    "00": "Consultation", "01": "Pharmacy", "02": "IPD", "03": "OPD", "04": "Pathology",
    "05": "Medicines", "06": "Nursing Charges", "07": "Handling Charges", "08": "Delivery Charges",
    "99": "Others",
}
_INVOICE_TYPES = frozenset({"00", "01", "02", "03", "99"})
#: HealthDoc's charge categories, mapped only where NRCeS has the concept.
_LINE_CODES = {
    "consultation": "00", "pharmacy": "05", "lab": "04", "ipd_stay": "02",
    "registration": "99", "radiology": "99", "procedure": "99", "blood": "99", "other": "99",
}
#: FHIR Invoice.status from HealthDoc's; a draft or cancelled bill is never shared.
_INVOICE_STATUS = {"issued": "issued", "partially_paid": "issued", "paid": "balanced", "waived": "balanced"}

_SECTION_CODES = {
    "chief_complaints": ("422843007", "Chief complaint section"),
    "diagnoses": ("371529009", "History and physical report"),
    "observations": ("425044008", "Physical exam section"),
    "allergies": ("722446000", "Allergy record"),
    "medications": ("721912009", "Medication summary document"),
    "prescription": ("440545006", "Prescription record"),
    "diagnostic_reports": ("721981007", "Diagnostic studies report"),
    "care_plan": ("734163000", "Care plan"),
    # ImmunizationRecord fixes its single section's code to the document code.
    "immunizations": ("41000179103", "Immunization record"),
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
            # A hospital UHID/THID is not an identifier issued by ABDM.
            "system": "https://healthdoc.world/identifiers/patient",
            "value": str(data["identifier"]),
        }
    ]
    if data.get("abha_number"):
        identifiers.append(
            {
                "type": {
                    "coding": [
                        {
                            "system": IDENTIFIER_TYPE,
                            "code": "MR",
                            "display": "Medical record number",
                        }
                    ]
                },
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
    if not data.get("id") or not str(data.get("name") or "").strip():
        raise ValueError("FHIR practitioner requires id and name")
    registration = str(data.get("registration_number") or "").strip()
    narrative = f"Practitioner: {data['name']}"
    if registration:
        code, display = "MD", "Medical License number"
        system, value = "https://doctor.abdm.gov.in", registration
    elif data.get("sandbox_account_id"):
        # The caller must opt in after its environment/document checks. This
        # identifies an existing local account, not an HPR or medical licence.
        account_id = str(uuid.UUID(str(data["sandbox_account_id"])))
        if account_id != str(data["id"]):
            raise ValueError("Sandbox practitioner identifier must match the source author")
        code, display = "AN", "Account number"
        system = "https://healthdoc.world/identifiers/sandbox-staff-account"
        value = account_id
        narrative = (
            f"Sandbox test practitioner account: {data['name']} (not a medical registration)"
        )
    else:
        raise ValueError(
            "FHIR practitioner requires registration_number or explicit sandbox account"
        )
    return {
        "resourceType": "Practitioner",
        "id": _rid("practitioner", data["id"]),
        "meta": _meta("Practitioner", authored_at),
        "text": _narrative(narrative),
        "identifier": [
            {
                "type": {
                    "coding": [
                        {
                            "system": IDENTIFIER_TYPE,
                            "code": code,
                            "display": display,
                        }
                    ]
                },
                "system": system,
                "value": value,
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
        if not conclusion or not modality:
            raise ValueError("FHIR imaging report requires modality and signed findings")
    if not is_lab:
        # DiagnosticReportImaging requires at least one media (NRCeS 6.5.0).
        # With a PACS study, the attachment is an explicit PACS-reference
        # document: HealthDoc stores the UID, not the DICOM bytes, so it never
        # labels a UID as application/dicom or invents image pixels. Without
        # one (no PACS at the facility), the attachment is the signed report
        # itself as text, titled as the report and never as an image.
        issued = _iso(item.get("issued") or authored_at)
        if pacs_study_uid:
            content = {
                "contentType": "application/json",
                "data": base64.b64encode(
                    json.dumps(
                        {"pacsStudyUid": pacs_study_uid, "modality": modality, "report": conclusion},
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode()
                ).decode(),
                "title": f"PACS study reference for {item['name']}",
                "creation": issued,
            }
            narrative, link_label = f"PACS study reference: {pacs_study_uid}", "PACS study reference"
        else:
            content = {
                "contentType": "text/plain",
                "data": base64.b64encode(
                    f"{item['name']} ({modality})\n\n{conclusion}\n".encode()
                ).decode(),
                "title": f"Signed report for {item['name']} (no images stored)",
                "creation": issued,
            }
            narrative, link_label = f"Signed report: {item['name']}", "Signed imaging report"
        media = {
            "resourceType": "Media",
            "id": _rid("media", item.get("id") or pacs_study_uid or f"{patient['id']}:{index}"),
            "meta": _meta("Media", authored_at),
            "text": _narrative(narrative),
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
            "createdDateTime": issued,
            "content": content,
        }
        attachments.append(media)
        report["media"] = [{"link": _reference(media, link_label)}]
    return report, observations, attachments


def _immunization(
    item: Mapping[str, Any],
    patient: Mapping[str, Any],
    practitioner: Mapping[str, Any],
    authored_at: datetime,
    index: int,
) -> dict[str, Any]:
    for required in ("vaccine", "occurred_at", "dose_number"):
        if not item.get(required):
            raise ValueError(f"FHIR immunization requires {required}")
    vaccine = str(item["vaccine"])
    dose = int(item["dose_number"])
    if dose < 1:
        raise ValueError("FHIR immunization dose number must be positive")
    protocol: dict[str, Any] = {"doseNumberPositiveInt": dose}
    if item.get("target_disease"):
        protocol["targetDisease"] = [{"text": str(item["target_disease"])}]
    resource: dict[str, Any] = {
        "resourceType": "Immunization",
        "id": _rid("immunization", item.get("id") or f"{patient['id']}:{index}:{vaccine}"),
        "meta": _meta("Immunization", authored_at),
        "text": _narrative(f"Immunization: {vaccine}, dose {dose}"),
        "status": "completed",
        # The catalogue holds HealthDoc's own codes (BCG, PENTAVALENT-1), not
        # SNOMED vaccine products. The NRCeS binding is only preferred, so the
        # vaccine travels as its catalogue name rather than a guessed concept.
        "vaccineCode": {"text": vaccine},
        "patient": _reference(patient),
        "occurrenceDateTime": _iso(item["occurred_at"]),
        "performer": [{"actor": _reference(practitioner)}],
        "protocolApplied": [protocol],
    }
    if item.get("lot_number"):
        resource["lotNumber"] = str(item["lot_number"])
    if item.get("expiration_date"):
        resource["expirationDate"] = _iso(item["expiration_date"])
    if item.get("manufacturer"):
        # Recorded as a name only; there is no Organization to point at.
        resource["manufacturer"] = {"display": str(item["manufacturer"])}
    # Site and route are stored as words (left_upper_arm, intramuscular). The
    # profile fixes route.coding to SNOMED, so neither is sent as a coding.
    for field in ("site", "route"):
        if item.get(field):
            resource[field] = {"text": str(item[field]).replace("_", " ")}
    notes = []
    if item.get("adverse_reaction"):
        # reaction.detail must reference an Observation that was never
        # recorded; the nurse's words are kept as an annotation instead.
        notes.append({"text": f"Adverse reaction: {item['adverse_reaction']}"})
    if item.get("notes"):
        notes.append({"text": str(item["notes"])})
    if notes:
        resource["note"] = notes
    return resource


def _money(value: Any) -> dict[str, Any]:
    return {"value": _json_value(Decimal(str(value))), "currency": "INR"}


def _price(kind: str, code: str, display: str, amount: Any) -> dict[str, Any]:
    return {
        "type": kind,
        "code": {"coding": [{"system": PRICE_COMPONENTS, "code": code, "display": display}]},
        "amount": _money(amount),
    }


def _invoice(
    data: Mapping[str, Any],
    patient: Mapping[str, Any],
    organization: Mapping[str, Any],
    authored_at: datetime,
) -> list[dict[str, Any]]:
    """The Invoice, then one ChargeItem per line (NRCeS Invoice, ChargeItem).

    HealthDoc charges no tax and discounts the whole bill, so each line
    carries its charged amount as the base price ("01 Rate") and the bill's
    discount and scheme adjustment travel as total price components. With no
    tax, FHIR's totalNet (tax excluded) and totalGross (tax included) are both
    the amount payable; HealthDoc's own "gross" is the pre-discount sum,
    which is not FHIR's gross.
    """
    for required in ("id", "number", "status", "type_code", "issued_at", "lines", "net_amount"):
        if data.get(required) in (None, "", []):
            raise ValueError(f"FHIR invoice requires {required}")
    status = _INVOICE_STATUS.get(str(data["status"]))
    if status is None:
        raise ValueError(f"A {data['status']} invoice is not shared")
    type_code = str(data["type_code"])
    if type_code not in _INVOICE_TYPES:
        raise ValueError(f"Unknown invoice type {type_code!r}")
    charge_items: list[dict[str, Any]] = []
    line_items: list[dict[str, Any]] = []
    for pos, line in enumerate(data["lines"]):
        code = _LINE_CODES.get(str(line.get("category")), "99")
        quantity = Decimal(str(line["quantity"]))
        if quantity <= 0 or not str(line.get("description") or "").strip():
            raise ValueError("FHIR charge item requires a description and a positive quantity")
        item = {
            "resourceType": "ChargeItem",
            "id": _rid("charge-item", line.get("id") or f"{data['id']}:{pos}"),
            "meta": _meta("ChargeItem", authored_at),
            "text": _narrative(f"{line['description']} x {quantity.normalize()}"),
            "status": "billed",
            "code": {"coding": [{"system": BILLING_CODES, "code": code, "display": _BILLING[code]}]},
            "subject": _reference(patient),
            "performer": [{"actor": _reference(organization)}],
            "quantity": {"value": _json_value(quantity)},
            # The line is a tariff entry, not a stocked product: named, not referenced.
            "productCodeableConcept": {"text": str(line["description"])},
        }
        charge_items.append(item)
        line_items.append({
            "sequence": pos + 1,
            "chargeItemReference": _reference(item),
            "priceComponent": [_price("base", "01", "Rate", line["amount"])],
        })
    totals = [
        _price("discount", "02", "Discount", value)
        for value in (data.get("discount_amount"), data.get("scheme_adjustment"))
        if value is not None and Decimal(str(value)) > 0
    ]
    resource: dict[str, Any] = {
        "resourceType": "Invoice",
        "id": _rid("invoice", data["id"]),
        "meta": _meta("Invoice", authored_at),
        "text": _narrative(f"Invoice {data['number']}"),
        "identifier": [{"value": str(data["number"])}],
        "status": status,
        "type": {"coding": [{"system": BILLING_CODES, "code": type_code, "display": _BILLING[type_code]}]},
        "subject": _reference(patient),
        "date": _iso(data["issued_at"]),
        "participant": [{"actor": _reference(organization)}],
        "issuer": _reference(organization),
        "lineItem": line_items,
        "totalNet": _money(data["net_amount"]),
        "totalGross": _money(data["net_amount"]),
    }
    if totals:
        resource["totalPriceComponent"] = totals
    return [resource, *charge_items]


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
    practitioner: Mapping[str, Any] | None,
    organization: Mapping[str, Any],
    encounter: Mapping[str, Any] | None,
    authored_at: datetime,
    care_context_reference: str,
    document_label: str | None = None,
    chief_complaints: Sequence[Mapping[str, Any]] = (),
    diagnoses: Sequence[Mapping[str, Any]] = (),
    allergies: Sequence[Mapping[str, Any]] = (),
    observations: Sequence[Mapping[str, Any]] = (),
    medications: Sequence[Mapping[str, Any]] = (),
    diagnostic_reports: Sequence[Mapping[str, Any]] = (),
    care_plan: str | None = None,
    immunizations: Sequence[Mapping[str, Any]] = (),
    invoice: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one transfer-ready FHIR document from explicit clinical facts."""
    if record_type not in _DOCUMENTS:
        raise ValueError(f"Unknown ABDM record type: {record_type!r}")
    if encounter is None and _DOCUMENTS[record_type][0] not in _ENCOUNTER_OPTIONAL:
        raise ValueError(f"{record_type} requires an encounter")
    immunization_record = record_type == "ImmunizationRecord"
    other_content = (
        chief_complaints, diagnoses, allergies, observations, medications, diagnostic_reports
    )
    # The ImmunizationRecord section is closed to anything but immunizations,
    # and immunizations belong to no other document type.
    if immunization_record and (any(other_content) or care_plan):
        raise ValueError("ImmunizationRecord carries immunizations only")
    if immunizations and not immunization_record:
        raise ValueError(f"{record_type} cannot carry immunizations")
    invoice_record = record_type == "Invoice"
    # InvoiceRecord has exactly one section, holding the Invoice.
    if invoice_record and (any(other_content) or care_plan or immunizations):
        raise ValueError("Invoice carries the invoice only")
    if invoice_record and not invoice:
        raise ValueError("Invoice has no invoice to transfer")
    if invoice and not invoice_record:
        raise ValueError(f"{record_type} cannot carry an invoice")
    # A bill is issued by the facility, not written by a health professional;
    # InvoiceRecord lets the Organization author it. Every other document
    # names its practitioner.
    # A laboratory report may be the laboratory's own (no registered author).
    lab_only = record_type == "DiagnosticReport" and bool(diagnostic_reports) and all(
        item.get("kind") == "lab" for item in diagnostic_reports
    ) and not any((chief_complaints, diagnoses, allergies, observations, medications))
    if practitioner is None and not invoice_record and not lab_only:
        raise ValueError(f"{record_type} requires a practitioner")
    profile, document_code, document_title = _DOCUMENTS[record_type]
    # Preserve the registered document label (including explicit test warnings)
    # without changing the profile's fixed/coded Composition.type vocabulary.
    composition_title = (document_label or "").strip() or document_title
    patient_resource = _patient(patient, authored_at)
    practitioner_resource = _practitioner(practitioner, authored_at) if practitioner is not None else None
    organization_resource = _organization(organization, authored_at)
    # Who performed and interpreted: the registered practitioner, or for a
    # laboratory's own report the laboratory (Organization) itself.
    performer_resource = practitioner_resource or organization_resource
    encounter_resource = (
        _encounter(encounter, patient_resource, authored_at) if encounter is not None else None
    )
    immunization_resources = [
        _immunization(item, patient_resource, practitioner_resource, authored_at, pos)
        for pos, item in enumerate(immunizations)
    ]

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
            performer_resource,
            authored_at,
            pos,
        )
        report_resources.append(report)
        report_observations.extend(result_observations)
        report_attachments.extend(attachments)

    invoice_resources: list[dict[str, Any]] = (
        _invoice(invoice, patient_resource, organization_resource, authored_at)
        if invoice_record and invoice
        else []
    )

    sections: list[dict[str, Any]] = []
    if invoice_resources:
        sections.append({"title": "Invoice details", "entry": [_reference(invoice_resources[0])]})
    candidates = (
        ("chief_complaints", complaints),
        ("diagnoses", conditions),
        ("observations", observation_resources),
        ("allergies", allergy_resources),
        ("medications", medication_resources),
        ("diagnostic_reports", report_resources),
        ("immunizations", immunization_resources),
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
        "text": _narrative(composition_title),
        "identifier": {
            "system": "https://healthdoc.world/fhir/document",
            "value": str(uuid.uuid4()),
        },
        "status": "final",
        "type": composition_type,
        "subject": _reference(patient_resource, str(patient["name"])),
        "date": _iso(authored_at),
        "author": [
            _reference(practitioner_resource, str(practitioner["name"]))
            if practitioner_resource is not None and practitioner is not None
            else _reference(organization_resource, str(organization["name"]))
        ],
        "title": composition_title,
        "custodian": _reference(organization_resource, str(organization["name"])),
        "section": sections,
    }
    if encounter_resource is not None:
        composition["encounter"] = _reference(encounter_resource)
    resources = [
        composition,
        *([practitioner_resource] if practitioner_resource is not None else []),
        organization_resource,
        patient_resource,
        *([encounter_resource] if encounter_resource is not None else []),
        *immunization_resources,
        *invoice_resources,
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
    content: dict[str, Any] = (
        {
            "encounter": None,
            "immunizations": [
                {"vaccine": "FHIR bundle shape test", "occurred_at": now, "dose_number": 1}
            ],
        }
        if record_type == "ImmunizationRecord"
        else {
            "encounter": None,
            "invoice": {
                "id": "shape-test", "number": "SHAPE-TEST-1", "status": "issued", "type_code": "03",
                "issued_at": now, "net_amount": Decimal("100.00"),
                "lines": [{"category": "consultation", "description": "FHIR bundle shape test",
                           "quantity": Decimal("1"), "amount": Decimal("100.00")}],
            },
        }
        if record_type == "Invoice"
        else {
            "encounter": {"id": care_context_id or "shape-test", "status": "closed"},
            "care_plan": "FHIR bundle shape test",
        }
    )
    return build_clinical_bundle(
        record_type,
        patient={
            "id": patient_id,
            "name": patient_id,
            "identifier": patient_id,
            "gender": "unknown",
        },
        practitioner=None
        if record_type == "Invoice"
        else {
            "id": author_hpr_id,
            "name": author_hpr_id,
            "registration_number": author_hpr_id,
        },
        organization={
            "id": "healthdoc",
            "name": "HealthDoc",
            "hfr_id": "test-only",
        },
        authored_at=now,
        care_context_reference=care_context_id or "shape-test",
        **content,
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
    profile_names = {
        str(url).rsplit("/", 1)[-1] for url in (first.get("meta") or {}).get("profile") or []
    }
    required_types = ["Patient", "Organization"]
    # A document authored by the facility (a bill, a laboratory's own report)
    # has no Practitioner to carry; any other document must name one.
    organization_ids = {
        f"urn:uuid:{entry['resource'].get('id')}"
        for entry in entries
        if entry.get("resource", {}).get("resourceType") == "Organization"
    }
    authors = {ref.get("reference") for ref in first.get("author") or [] if isinstance(ref, dict)}
    facility_authored = bool(authors) and authors <= organization_ids
    if "InvoiceRecord" not in profile_names and not facility_authored:
        required_types.append("Practitioner")
    if profile_names.isdisjoint(_ENCOUNTER_OPTIONAL):
        required_types.append("Encounter")
    for required in required_types:
        if not any(entry.get("resource", {}).get("resourceType") == required for entry in entries):
            errors.append(f"bundle must contain a {required}")
    return errors

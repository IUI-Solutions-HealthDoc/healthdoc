"""FHIR-shaped stub builders — B3-W4-02 (#201).

These build structurally FHIR-R4-like dicts (Composition, MedicationRequest)
for OPD notes and prescriptions when an encounter closes. They are STUBS:
enough shape to store/inspect/push later via the HIP flow, not full spec
validation. Real ABDM HIP push wiring is future work (see
app/integrations/abdm/hip/).
"""
import uuid
from datetime import datetime, timezone
from typing import Any


def build_opd_note_composition(
    encounter_id: uuid.UUID,
    patient_id: uuid.UUID,
    subjective: str | None,
    objective: str | None,
    assessment: str | None,
    plan: str | None,
) -> dict[str, Any]:
    """Stub FHIR Composition resource summarizing the SOAP note."""
    now = datetime.now(timezone.utc).isoformat()
    sections = []
    for title, code, text in [
        ("Subjective", "subjective", subjective),
        ("Objective", "objective", objective),
        ("Assessment", "assessment", assessment),
        ("Plan", "plan", plan),
    ]:
        if text:
            sections.append({
                "title": title,
                "code": {"text": code},
                "text": {"status": "generated", "div": f"<div>{text}</div>"},
            })

    return {
        "resourceType": "Composition",
        "id": str(uuid.uuid4()),
        "status": "final",
        "type": {"text": "OPD Consultation Note"},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "date": now,
        "title": "OPD Consultation Note",
        "section": sections,
    }


def build_medication_request(
    patient_id: uuid.UUID,
    encounter_id: uuid.UUID,
    prescription_id: uuid.UUID,
    medicine_name: str,
    dosage: str | None,
    frequency: str | None,
    duration_days: int | None,
    route: str | None,
    instructions: str | None,
) -> dict[str, Any]:
    """Stub FHIR MedicationRequest resource for one prescription item."""
    now = datetime.now(timezone.utc).isoformat()
    dosage_instruction: dict[str, Any] = {"text": " ".join(
        filter(None, [dosage, frequency, f"for {duration_days} days" if duration_days else None])
    )}
    if route:
        dosage_instruction["route"] = {"text": route}
    if instructions:
        dosage_instruction["patientInstruction"] = instructions

    return {
        "resourceType": "MedicationRequest",
        "id": str(uuid.uuid4()),
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {"text": medicine_name},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "authoredOn": now,
        "dosageInstruction": [dosage_instruction],
        "extension": [
            {"url": "prescription_id", "valueString": str(prescription_id)},
        ],
    }
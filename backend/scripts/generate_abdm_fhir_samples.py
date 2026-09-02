"""Generate deterministic-content ABDM FHIR samples for profile validation.

The output is intentionally synthetic and must never be sent to the sandbox.
It exists so the official HL7 validator can exercise every mapper shape without
requiring access to a patient database.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

from app.integrations.abdm.fhir.builder import build_clinical_bundle


def _common() -> dict:
    return {
        "patient": {
            "id": "validation-patient",
            "name": "Validation Patient",
            "identifier": "VALIDATION-UHID",
            "gender": "unknown",
            "birth_date": date(1990, 1, 1),
        },
        "practitioner": {
            "id": "validation-practitioner",
            "name": "Validation Practitioner",
            "registration_number": "VALIDATION-HPR",
        },
        "organization": {
            "id": "validation-facility",
            "name": "Validation Facility",
            "hfr_id": "VALIDATION-HFR",
        },
        "encounter": {
            "id": "validation-visit",
            "status": "completed",
            "class": "AMB",
        },
        "authored_at": datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        "care_context_reference": "validation-visit",
    }


def _samples() -> dict[str, dict]:
    common = _common()
    return {
        "OPConsultation": build_clinical_bundle(
            "OPConsultation",
            **common,
            diagnoses=[{"id": "diagnosis-1", "text": "Viral fever", "code": "B34.9"}],
        ),
        "DiagnosticReport": build_clinical_bundle(
            "DiagnosticReport",
            **common,
            diagnostic_reports=[
                {
                    "id": "lab-result-1",
                    "kind": "lab",
                    "name": "Haemoglobin",
                    "issued": common["authored_at"],
                    "observations": [{"name": "Haemoglobin", "value": 13.2, "unit": "g/dL"}],
                }
            ],
        ),
        "DiagnosticReportImaging": build_clinical_bundle(
            "DiagnosticReport",
            **common,
            diagnostic_reports=[
                {
                    "id": "imaging-result-1",
                    "kind": "radiology",
                    "name": "Chest radiograph",
                    "modality": "xray",
                    "pacs_study_uid": "1.2.840.113619.2.55.3.604688433.1",
                    "issued": common["authored_at"],
                    "conclusion": "No acute cardiopulmonary finding.",
                }
            ],
        ),
        "Prescription": build_clinical_bundle(
            "Prescription",
            **common,
            medications=[
                {
                    "id": "medication-1",
                    "name": "Recorded medicine",
                    "dosage": "One tablet",
                    "frequency": "Twice daily",
                }
            ],
        ),
        "DischargeSummary": build_clinical_bundle(
            "DischargeSummary",
            **common,
            care_plan="Patient discharged with follow-up instructions.",
        ),
        "WellnessRecord": build_clinical_bundle(
            "WellnessRecord",
            **common,
            observations=[{"name": "Pulse rate", "value": 72, "unit": "/min"}],
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, bundle in _samples().items():
        (args.output / f"{name}.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

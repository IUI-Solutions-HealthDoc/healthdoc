"""Generate deterministic-content ABDM FHIR samples for profile validation.

The output is intentionally synthetic and must never be sent to the sandbox.
It exists so the official HL7 validator can exercise every mapper shape without
requiring access to a patient database.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from app.integrations.abdm.fhir.builder import build_clinical_bundle


def _common() -> dict:
    return {
        "patient": {
            "id": "validation-patient",
            "name": "Validation Patient",
            "identifier": "VALIDATION-UHID",
            # Exercise the second identifier too: samples without ABHA hid a
            # missing mandatory Patient.identifier.type in the live exporter.
            "abha_number": "91000000000001",
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
        "Invoice": build_clinical_bundle(
            "Invoice",
            **{**common, "encounter": None, "practitioner": None},
            invoice={
                "id": "validation-invoice", "number": "VALIDATION-INV-1", "status": "paid",
                "type_code": "03", "issued_at": common["authored_at"], "net_amount": Decimal("450.00"),
                "discount_amount": Decimal("50.00"),
                "lines": [
                    {"id": "validation-line-1", "category": "consultation", "description": "OPD consultation",
                     "quantity": Decimal("1"), "amount": Decimal("400.00")},
                    {"id": "validation-line-2", "category": "pharmacy", "description": "Paracetamol 500 mg",
                     "quantity": Decimal("10"), "amount": Decimal("100.00")},
                ],
            },
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

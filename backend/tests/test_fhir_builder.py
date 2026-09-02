from datetime import UTC, date, datetime

import pytest

from app.integrations.abdm.fhir.builder import (
    RECORD_TYPES,
    build_all,
    build_bundle,
    build_clinical_bundle,
    validate_min,
)


def test_all_five_record_types_valid():
    bundles = build_all("patient-123", "HPR-9999")
    assert set(bundles) == set(RECORD_TYPES)
    assert len(RECORD_TYPES) == 5
    for rt, b in bundles.items():
        assert validate_min(b) == [], (rt, validate_min(b))


def test_bundle_shape():
    b = build_bundle("Prescription", patient_id="p1", author_hpr_id="HPR1")
    assert b["resourceType"] == "Bundle"
    assert b["type"] == "document"
    assert b["entry"][0]["resource"]["resourceType"] == "Composition"


def test_unknown_type_rejected():
    with pytest.raises(ValueError):
        build_bundle("NotAThing", patient_id="p1", author_hpr_id="HPR1")


def _facts():
    return {
        "patient": {
            "id": "patient-1",
            "name": "Patient One",
            "identifier": "UHID-1",
            "gender": "female",
            "birth_date": date(1990, 1, 2),
        },
        "practitioner": {
            "id": "doctor-1",
            "name": "Dr One",
            "registration_number": "HPR-1",
        },
        "organization": {
            "id": "facility-1",
            "name": "Facility One",
            "hfr_id": "HFR-1",
        },
        "encounter": {"id": "visit-1", "status": "completed", "class": "AMB"},
        "authored_at": datetime(2026, 1, 2, tzinfo=UTC),
        "care_context_reference": "visit-1",
    }


def test_wellness_uses_the_profile_fixed_text_not_an_invented_snomed_code():
    bundle = build_clinical_bundle(
        "WellnessRecord",
        **_facts(),
        observations=[{"name": "Pulse rate", "value": 72, "unit": "/min"}],
    )
    composition = bundle["entry"][0]["resource"]
    assert composition["type"] == {"text": "Wellness Record"}


def test_optional_fhir_arrays_are_omitted_instead_of_serialised_empty():
    facts = _facts()
    bundle = build_clinical_bundle(
        "DiagnosticReport",
        **facts,
        diagnostic_reports=[
            {
                "id": "radiology-1",
                "kind": "radiology",
                "modality": "xray",
                "pacs_study_uid": "1.2.840.113619.2.55.3.604688433.1",
                "name": "Chest radiograph",
                "conclusion": "No acute finding",
                "observations": [],
            }
        ],
    )
    report = next(
        entry["resource"]
        for entry in bundle["entry"]
        if entry["resource"]["resourceType"] == "DiagnosticReport"
    )
    assert report["meta"]["profile"] == [
        "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportImaging"
    ]
    assert "result" not in report
    assert report["media"]


def test_imaging_never_claims_a_pacs_uid_is_an_image():
    bundle = build_clinical_bundle(
        "DiagnosticReport",
        **_facts(),
        diagnostic_reports=[
            {
                "id": "radiology-1",
                "kind": "radiology",
                "modality": "ct",
                "pacs_study_uid": "1.2.840.113619.2.55.3.604688433.1",
                "name": "CT head",
                "conclusion": "No acute finding",
                "observations": [],
            }
        ],
    )
    media = next(
        entry["resource"]
        for entry in bundle["entry"]
        if entry["resource"]["resourceType"] == "Media"
    )
    assert media["content"]["contentType"] == "application/json"
    assert media["content"]["contentType"] != "application/dicom"


def test_imaging_without_retrievable_study_reference_fails_closed():
    with pytest.raises(ValueError, match="PACS study UID"):
        build_clinical_bundle(
            "DiagnosticReport",
            **_facts(),
            diagnostic_reports=[
                {
                    "id": "radiology-1",
                    "kind": "radiology",
                    "modality": "xray",
                    "name": "Chest radiograph",
                    "conclusion": "No acute finding",
                    "observations": [],
                }
            ],
        )


def test_document_graph_uses_resolvable_absolute_uuid_references():
    bundle = build_clinical_bundle(
        "WellnessRecord",
        **_facts(),
        observations=[{"name": "Pulse rate", "value": 72, "unit": "/min"}],
    )
    full_urls = {entry["fullUrl"] for entry in bundle["entry"]}
    assert all(value.startswith("urn:uuid:") for value in full_urls)
    composition = bundle["entry"][0]["resource"]
    assert composition["subject"]["reference"] in full_urls
    assert composition["section"][0]["entry"][0]["reference"] in full_urls


def test_a_text_only_diagnosis_does_not_emit_an_empty_coding_array():
    bundle = build_clinical_bundle(
        "OPConsultation",
        **_facts(),
        diagnoses=[{"text": "Viral fever"}],
    )
    condition = next(
        entry["resource"]
        for entry in bundle["entry"]
        if entry["resource"]["resourceType"] == "Condition"
    )
    assert condition["code"] == {"text": "Viral fever"}

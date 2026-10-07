from datetime import UTC, date, datetime
from decimal import Decimal
from xml.etree import ElementTree

import pytest

from app.integrations.abdm.fhir.builder import (
    RECORD_TYPES,
    build_all,
    build_bundle,
    build_clinical_bundle,
    validate_min,
)


def test_all_seven_record_types_valid():
    bundles = build_all("patient-123", "HPR-9999")
    assert set(bundles) == set(RECORD_TYPES)
    assert len(RECORD_TYPES) == 7
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


@pytest.mark.parametrize("abha", [None, "91000000000001"])
def test_patient_identifiers_are_typed_and_do_not_confuse_uhid_with_abha(abha):
    facts = _facts()
    facts["patient"]["abha_number"] = abha
    bundle = build_clinical_bundle(
        "WellnessRecord",
        **facts,
        observations=[{"name": "Pulse rate", "value": 72, "unit": "/min"}],
    )
    patient = next(
        e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Patient"
    )
    identifiers = patient["identifier"]
    assert len(identifiers) == (2 if abha else 1)
    assert identifiers[0]["system"] == "https://healthdoc.world/identifiers/patient"
    assert identifiers[0]["value"] == "UHID-1"
    if abha:
        assert identifiers[1]["system"] == "https://healthid.abdm.gov.in"
        assert identifiers[1]["value"] == abha
    for identifier in identifiers:
        assert identifier["type"]["coding"] == [
            {
                "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                "code": "MR",
                "display": "Medical record number",
            }
        ]


def test_explicit_sandbox_account_identifier_does_not_claim_a_medical_licence():
    facts = _facts()
    account_id = "c20f23da-3694-4a9d-b575-242e830f23d3"
    facts["practitioner"] = {
        "id": account_id,
        "name": "Sandbox Test Author",
        "sandbox_account_id": account_id,
    }
    bundle = build_clinical_bundle(
        "WellnessRecord",
        **facts,
        observations=[{"name": "Pulse rate", "value": 72, "unit": "/min"}],
    )
    author = next(
        e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Practitioner"
    )
    assert author["name"] == [{"text": "Sandbox Test Author"}]
    assert author["identifier"] == [
        {
            "type": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "AN",
                        "display": "Account number",
                    }
                ]
            },
            "system": "https://healthdoc.world/identifiers/sandbox-staff-account",
            "value": account_id,
        }
    ]
    assert "not a medical registration" in author["text"]["div"]


@pytest.mark.parametrize("account_id", [None, "", "not-a-uuid", "doctor-1"])
def test_missing_or_invented_practitioner_identity_is_still_refused(account_id):
    facts = _facts()
    facts["practitioner"].pop("registration_number")
    facts["practitioner"]["sandbox_account_id"] = account_id
    with pytest.raises(ValueError, match="registration_number|UUID"):
        build_clinical_bundle("WellnessRecord", **facts)


def test_sandbox_identifier_cannot_impersonate_a_different_account():
    facts = _facts()
    facts["practitioner"].pop("registration_number")
    facts["practitioner"]["sandbox_account_id"] = "c20f23da-3694-4a9d-b575-242e830f23d3"
    with pytest.raises(ValueError, match="match the source author"):
        build_clinical_bundle("WellnessRecord", **facts)


def _dose(**changes):
    return {
        "id": "dose-1",
        "vaccine": "Test vaccine",
        "occurred_at": datetime(2026, 1, 2, tzinfo=UTC),
        "dose_number": 1,
        **changes,
    }


@pytest.mark.parametrize("record_type", RECORD_TYPES)
def test_document_label_survives_export_without_changing_the_profile_type(record_type):
    facts = (
        {**_facts(), "encounter": None, "immunizations": [_dose()]}
        if record_type == "ImmunizationRecord"
        else {**_facts(), "encounter": None, "practitioner": None, "invoice": _bill()}
        if record_type == "Invoice"
        else {**_facts(), "care_plan": "Synthetic test content"}
    )
    original = build_clinical_bundle(record_type, **facts)["entry"][0]["resource"]
    label = "ABDM SANDBOX TEST — SYNTHETIC <not clinical advice> & test only"
    composition = build_clinical_bundle(record_type, **facts, document_label=label)["entry"][0][
        "resource"
    ]
    assert composition["title"] == label
    assert composition["type"] == original["type"]
    narrative = ElementTree.fromstring(composition["text"]["div"])
    assert narrative.text == label
    assert list(narrative) == []  # A label is text, never executable markup.


@pytest.mark.parametrize("label", [None, "", " \t\n"])
def test_absent_document_label_keeps_the_standard_title(label):
    composition = build_clinical_bundle(
        "WellnessRecord",
        **_facts(),
        observations=[{"name": "Pulse rate", "value": 72, "unit": "/min"}],
        document_label=label,
    )["entry"][0]["resource"]
    assert composition["title"] == "Wellness Record"


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


def _resources(bundle, kind):
    return [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == kind]


_XRAY = {
    "id": "radiology-1",
    "kind": "radiology",
    "modality": "xray",
    "name": "Chest radiograph",
    "conclusion": "No acute finding",
    "observations": [],
}


def test_imaging_without_a_pacs_study_carries_the_signed_report_not_an_image():
    # NRCeS DiagnosticReportImaging needs one media; a facility with no PACS
    # still has a signed report (live, 6 Oct 2026: every X-ray failed here).
    bundle = build_clinical_bundle("DiagnosticReport", **_facts(), diagnostic_reports=[_XRAY])
    (media,) = _resources(bundle, "Media")
    assert media["content"]["contentType"] == "text/plain"
    assert "no images stored" in media["content"]["title"]
    assert "PACS" not in media["text"]["div"]
    (report,) = _resources(bundle, "DiagnosticReport")
    assert report["media"][0]["link"]["reference"] == f"urn:uuid:{media['id']}"


def test_imaging_with_a_pacs_study_still_carries_the_pacs_reference():
    bundle = build_clinical_bundle(
        "DiagnosticReport", **_facts(), diagnostic_reports=[{**_XRAY, "pacs_study_uid": "2.25.1"}])
    (media,) = _resources(bundle, "Media")
    assert media["content"]["contentType"] == "application/json"
    assert media["content"]["title"].startswith("PACS study reference")


def test_imaging_without_signed_findings_fails_closed():
    with pytest.raises(ValueError, match="signed findings"):
        build_clinical_bundle(
            "DiagnosticReport", **_facts(), diagnostic_reports=[{**_XRAY, "conclusion": ""}])


_CBC = {
    "id": "lab-1",
    "kind": "lab",
    "name": "Complete Blood Count",
    "observations": [{"id": "o1", "name": "Haemoglobin", "value": 9.4, "unit": "g/dL"}],
}


def test_a_laboratory_report_without_a_registered_author_is_the_facilitys():
    bundle = build_clinical_bundle(
        "DiagnosticReport", **{**_facts(), "practitioner": None}, diagnostic_reports=[_CBC])
    assert _resources(bundle, "Practitioner") == []
    (organization,) = _resources(bundle, "Organization")
    organization_ref = f"urn:uuid:{organization['id']}"
    (composition,) = _resources(bundle, "Composition")
    assert [a["reference"] for a in composition["author"]] == [organization_ref]
    (report,) = _resources(bundle, "DiagnosticReport")
    assert report["resultsInterpreter"][0]["reference"] == organization_ref
    assert all(o["performer"][0]["reference"] == organization_ref
               for o in _resources(bundle, "Observation"))


@pytest.mark.parametrize(
    ("record_type", "content"),
    [("DiagnosticReport", {"diagnostic_reports": [_XRAY]}),
     ("DiagnosticReport", {"diagnostic_reports": [_CBC, _XRAY]}),
     ("OPConsultation", {"chief_complaints": [{"text": "Cough"}]})],
)
def test_only_a_laboratory_report_may_omit_its_practitioner(record_type, content):
    with pytest.raises(ValueError, match="requires a practitioner"):
        build_clinical_bundle(record_type, **{**_facts(), "practitioner": None}, **content)


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


def test_an_immunization_record_needs_no_encounter_and_holds_one_coded_section():
    bundle = build_clinical_bundle(
        "ImmunizationRecord", **{**_facts(), "encounter": None}, immunizations=[_dose()]
    )
    assert validate_min(bundle) == []
    kinds = [entry["resource"]["resourceType"] for entry in bundle["entry"]]
    assert "Encounter" not in kinds and kinds.count("Immunization") == 1
    composition = bundle["entry"][0]["resource"]
    assert composition["meta"]["profile"] == [
        "https://nrces.in/ndhm/fhir/r4/StructureDefinition/ImmunizationRecord"
    ]
    assert "encounter" not in composition
    coding = {"system": "http://snomed.info/sct", "code": "41000179103",
              "display": "Immunization record"}
    assert composition["type"]["coding"] == [coding]
    assert [section["code"]["coding"] for section in composition["section"]] == [[coding]]


def test_vaccine_site_and_route_travel_as_text_not_as_guessed_codes():
    bundle = build_clinical_bundle(
        "ImmunizationRecord", **{**_facts(), "encounter": None},
        immunizations=[_dose(site="left_upper_arm", route="intradermal")],
    )
    immunization = bundle["entry"][-1]["resource"]
    assert immunization["vaccineCode"] == {"text": "Test vaccine"}
    assert immunization["site"] == {"text": "left upper arm"}
    assert immunization["route"] == {"text": "intradermal"}
    assert "note" not in immunization and "lotNumber" not in immunization


@pytest.mark.parametrize("missing", ["vaccine", "occurred_at", "dose_number"])
def test_an_immunization_without_its_required_facts_is_refused(missing):
    with pytest.raises(ValueError, match=missing):
        build_clinical_bundle(
            "ImmunizationRecord", **{**_facts(), "encounter": None},
            immunizations=[_dose(**{missing: None})],
        )


@pytest.mark.parametrize(
    "extra",
    [{"care_plan": "Plan"}, {"diagnoses": [{"text": "Fever"}]},
     {"observations": [{"name": "Pulse rate", "value": 72, "unit": "/min"}]}],
)
def test_an_immunization_record_carries_nothing_but_immunizations(extra):
    with pytest.raises(ValueError, match="immunizations only"):
        build_clinical_bundle(
            "ImmunizationRecord", **{**_facts(), "encounter": None},
            immunizations=[_dose()], **extra,
        )


@pytest.mark.parametrize(
    "record_type", [t for t in RECORD_TYPES if t not in {"ImmunizationRecord", "Invoice"}]
)
def test_every_other_document_still_requires_an_encounter_and_refuses_doses(record_type):
    with pytest.raises(ValueError, match="requires an encounter"):
        build_clinical_bundle(
            record_type, **{**_facts(), "encounter": None}, care_plan="Synthetic test content"
        )
    with pytest.raises(ValueError, match="cannot carry immunizations"):
        build_clinical_bundle(record_type, **_facts(), immunizations=[_dose()])


def test_the_minimum_check_still_demands_an_encounter_outside_immunization_records():
    bundle = build_clinical_bundle("WellnessRecord", **_facts(), care_plan="Synthetic")
    bundle["entry"] = [
        entry for entry in bundle["entry"] if entry["resource"]["resourceType"] != "Encounter"
    ]
    assert validate_min(bundle) == ["bundle must contain a Encounter"]

def _bill() -> dict:
    return {
        "id": "bill-1", "number": "INV-TEST-1", "status": "paid", "type_code": "03",
        "issued_at": datetime(2026, 10, 5, 9, 0, tzinfo=UTC), "net_amount": Decimal("450.00"),
        "discount_amount": Decimal("50.00"), "scheme_adjustment": Decimal("0"),
        "lines": [
            {"id": "l1", "category": "consultation", "description": "OPD consultation",
             "quantity": Decimal("1"), "amount": Decimal("400.00")},
            {"id": "l2", "category": "pharmacy", "description": "Paracetamol 500 mg",
             "quantity": Decimal("10"), "amount": Decimal("100.00")},
        ],
    }


def test_an_invoice_record_is_authored_by_the_facility_and_carries_only_the_bill():
    bundle = build_clinical_bundle("Invoice", **{**_facts(), "encounter": None, "practitioner": None},
                                   invoice=_bill())
    assert validate_min(bundle) == []
    kinds = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert kinds == ["Composition", "Organization", "Patient", "Invoice", "ChargeItem", "ChargeItem"]
    invoice = bundle["entry"][3]["resource"]
    assert invoice["status"] == "balanced"
    assert invoice["totalNet"] == invoice["totalGross"] == {"value": 450.0, "currency": "INR"}
    assert invoice["totalPriceComponent"][0]["type"] == "discount"
    assert invoice["totalPriceComponent"][0]["amount"]["value"] == 50.0
    medicines = bundle["entry"][5]["resource"]
    assert medicines["code"]["coding"][0]["code"] == "05" and medicines["quantity"] == {"value": 10.0}


@pytest.mark.parametrize("status", ["draft", "cancelled"])
def test_a_draft_or_cancelled_bill_is_never_built(status):
    with pytest.raises(ValueError, match="not shared"):
        build_clinical_bundle("Invoice", **{**_facts(), "encounter": None, "practitioner": None},
                              invoice={**_bill(), "status": status})


def test_an_invoice_carries_no_clinical_content_and_others_carry_no_invoice():
    with pytest.raises(ValueError, match="invoice only"):
        build_clinical_bundle("Invoice", **{**_facts(), "practitioner": None}, invoice=_bill(),
                              care_plan="Synthetic")
    with pytest.raises(ValueError, match="cannot carry an invoice"):
        build_clinical_bundle("OPConsultation", **_facts(), invoice=_bill(), care_plan="Synthetic")
    with pytest.raises(ValueError, match="requires a practitioner"):
        build_clinical_bundle("OPConsultation", **{**_facts(), "practitioner": None}, care_plan="Synthetic")

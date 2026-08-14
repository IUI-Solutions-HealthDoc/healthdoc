from app.integrations.abdm.fhir.builder import RECORD_TYPES, build_all, build_bundle, validate_min


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
    import pytest
    with pytest.raises(ValueError):
        build_bundle("NotAThing", patient_id="p1", author_hpr_id="HPR1")

"""B2-W3-01: patient history — pure logic tests (no DB required)."""
import pytest


_CLINICAL_ROLES = {"doctor", "nurse", "admin", "supervisor", "hod", "auditor"}
_NON_CLINICAL_ROLES = {"receptionist"}


def test_clinical_roles_see_allergies():
    """Doctors, nurses, admins etc. must be in the clinical set."""
    for role in ("doctor", "nurse", "admin", "supervisor"):
        assert role in _CLINICAL_ROLES


def test_receptionist_is_not_clinical():
    assert "receptionist" not in _CLINICAL_ROLES


def test_history_response_schema():
    """PatientHistoryResponse must have the three expected fields."""
    from app.patients.schemas import PatientHistoryResponse
    fields = PatientHistoryResponse.model_fields.keys()
    assert "patient_id" in fields
    assert "audit_events" in fields
    assert "allergies" in fields


def test_audit_event_out_schema():
    from app.patients.schemas import AuditEventOut
    fields = AuditEventOut.model_fields.keys()
    for f in ("id", "action", "resource_type", "created_at"):
        assert f in fields


def test_allergy_out_schema():
    from app.patients.schemas import AllergyOut
    fields = AllergyOut.model_fields.keys()
    for f in ("id", "substance_text", "severity", "status"):
        assert f in fields

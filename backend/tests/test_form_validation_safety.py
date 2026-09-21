import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.forms.models import FormDefinition, FormSubmission
from app.forms.schemas import FormDefinitionCreate, FormFieldDef, FormSubmissionCreate
from app.forms.service import create_submission
from app.forms.validation import validate_submission
from app.patients.models import Patient

FIELDS = [
    {"id": "value", "label": "Measured value", "type": "number", "required": True},
    {"id": "choice", "label": "Choice", "type": "select", "options": [{"label": "First", "value": "one"}]},
    {"id": "reviewed", "label": "Reviewed", "type": "checkbox"},
    {"id": "day", "label": "Date", "type": "date"},
]


@pytest.mark.parametrize("fields", [
    [], [{"id": "a", "label": "A", "type": "script"}],
    [{"id": "a", "label": "A", "type": "text", "onChange": "execute()"}],
    [FIELDS[0], FIELDS[0]], [{"id": "bad id", "label": "A", "type": "text"}],
    [{"id": "a", "label": "A", "type": "select", "options": []}],
    [{"id": "a", "label": "A", "type": "select", "options": [{"label": "A", "value": "x"}, {"label": "B", "value": "x"}]}],
])
def test_malformed_or_executable_form_definitions_rejected(fields):
    with pytest.raises(ValidationError):
        FormDefinitionCreate(code="TEST", title="Test Form", fields_schema=fields)


@pytest.mark.parametrize("data", [
    {"value": True}, {"value": "12"}, {"value": float("nan")}, {"value": float("inf")},
    {"value": 10**1000}, {"value": []}, {"value": 12, "choice": "First"},
    {"value": 12, "reviewed": "false"}, {"value": 12, "day": "2026-02-30"},
    {"value": 12, "day": "2026-01-01T00:00:00"}, {"value": 12, "unexpected": "field"},
])
def test_submission_values_must_match_stored_field_types(data):
    with pytest.raises(ValueError):
        validate_submission([FormFieldDef.model_validate(field) for field in FIELDS], data)


@pytest.mark.asyncio
async def test_invalid_response_cannot_write_and_valid_decimals_false_and_codes_read_back(db, seed):
    dept, _, actor = seed
    patient = Patient(id=uuid.uuid4(), uhid="TEST-FORM-ONLY", full_name="Synthetic Form",
                      sex="unknown", age_years=30, identity_path="demographics_only",
                      facility_id=dept.facility_id, created_by=actor.id)
    definition = FormDefinition(id=uuid.uuid4(), code="TEST", title="Test Form", version=3,
                                fields_schema=FIELDS, status="published", created_by=actor.id)
    db.add_all([patient, definition])
    await db.flush()
    with pytest.raises(ValueError):
        await create_submission(db, FormSubmissionCreate(patient_id=patient.id, form_id=definition.id,
                                form_data={"value": "secret-invalid-clinical-input"}), actor.id)
    assert await db.scalar(select(func.count()).select_from(FormSubmission)) == 0
    payload = {"value": 12.5, "choice": "one", "reviewed": False, "day": "2026-01-01"}
    result = await create_submission(db, FormSubmissionCreate(patient_id=patient.id, form_id=definition.id,
                                     form_data=payload), actor.id)
    assert result.form_data == payload
    assert result.form_version == 3
    assert result.patient_id == patient.id

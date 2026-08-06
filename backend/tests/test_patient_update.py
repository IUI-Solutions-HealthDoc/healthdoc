"""B2-W2-03: patient update — schema tests (no DB required)."""
import uuid
import pytest
from pydantic import ValidationError
from app.patients.schemas import PatientUpdate


def test_update_requires_at_least_one_field():
    with pytest.raises(ValidationError):
        PatientUpdate()


def test_update_accepts_single_field():
    p = PatientUpdate(full_name="Ramesh Kumar")
    assert p.full_name == "Ramesh Kumar"
    assert p.mobile is None


def test_update_accepts_multiple_fields():
    p = PatientUpdate(full_name="Sita Devi", mobile="9876543210", district="Ajmer")
    assert p.district == "Ajmer"


def test_update_does_not_expose_identity_fields():
    fields = PatientUpdate.model_fields.keys()
    for forbidden in ("uhid", "thid", "status", "identity_path", "identity_status"):
        assert forbidden not in fields, f"{forbidden} must not be patchable"


def test_update_photo_file_id_accepts_uuid():
    fid = uuid.uuid4()
    p = PatientUpdate(photo_file_id=fid)
    assert p.photo_file_id == fid

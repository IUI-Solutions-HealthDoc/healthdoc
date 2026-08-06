"""B2-W2-01: files module — pure logic tests (no DB or MinIO required)."""
import uuid
import pytest


def test_object_name_convention():
    patient_id = uuid.uuid4()
    file_id = uuid.uuid4()
    object_name = f"patients/{patient_id}/photo/{file_id}"
    parts = object_name.split("/")
    assert parts[0] == "patients"
    assert parts[2] == "photo"
    assert uuid.UUID(parts[1]) == patient_id
    assert uuid.UUID(parts[3]) == file_id


def test_allowed_content_types():
    from app.files.router import _ALLOWED_CONTENT_TYPES
    assert "image/jpeg" in _ALLOWED_CONTENT_TYPES
    assert "image/png" in _ALLOWED_CONTENT_TYPES
    assert "image/webp" in _ALLOWED_CONTENT_TYPES
    assert "application/pdf" not in _ALLOWED_CONTENT_TYPES


def test_max_photo_size_is_5mb():
    from app.files.router import _MAX_PHOTO_BYTES
    assert _MAX_PHOTO_BYTES == 5 * 1024 * 1024


def test_storage_client_singleton():
    from app.common.storage import get_storage
    assert get_storage() is get_storage()

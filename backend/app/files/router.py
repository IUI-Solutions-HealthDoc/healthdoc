"""files module router — B2-W2-01: photo upload for patient registration."""
import uuid
import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.storage import get_storage, StorageClient
from app.patients.models import Patient

router = APIRouter(prefix="/files", tags=["files"])

_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB


class PhotoUploadOut(BaseModel):
    file_id: uuid.UUID
    patient_id: uuid.UUID
    url: str


class PhotoUrlOut(BaseModel):
    file_id: uuid.UUID
    patient_id: uuid.UUID
    url: str


@router.get("/ping")
async def ping() -> dict:
    return {"module": "files", "status": "ok"}


@router.post(
    "/patients/{patient_id}/photo",
    response_model=PhotoUploadOut,
    status_code=201,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def upload_patient_photo(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    storage: StorageClient = Depends(get_storage),
    file: UploadFile = File(...),
) -> PhotoUploadOut:
    """Upload a patient photo to MinIO; stores file_id on patient row.
    Re-uploading replaces the existing photo in-place (same file_id)."""
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(415, {"code": "unsupported_media_type",
            "message": f"Photo must be jpeg, png, or webp — got {file.content_type}"})

    data = await file.read()
    if len(data) > _MAX_PHOTO_BYTES:
        raise HTTPException(413, {"code": "file_too_large",
            "message": f"Photo must be under 5 MB — got {len(data)/1024/1024:.1f} MB"})

    patient = await db.get(Patient, patient_id)
    if not patient or patient.facility_id != current_db_user.facility_id or patient.deleted_at is not None:
        raise HTTPException(404, {"code": "patient_not_found"})
    if patient.status != "active":
        raise HTTPException(409, {"code": "patient_not_active"})

    # Reuse existing file_id so re-upload replaces in place
    file_id = patient.photo_file_id or uuid.uuid4()
    object_name = f"patients/{patient_id}/photo/{file_id}"

    # Upload to MinIO first — DB unchanged if this fails
    await storage.put_object(object_name, data, content_type=file.content_type)

    patient.photo_file_id = file_id
    patient.updated_by = current_db_user.id
    patient.row_version = patient.row_version + 1
    await db.flush()

    url = await storage.presign_get(object_name, expires_seconds=3600)
    return PhotoUploadOut(file_id=file_id, patient_id=patient_id, url=url)


@router.get(
    "/patients/{patient_id}/photo",
    response_model=PhotoUrlOut,
    dependencies=[Depends(require_roles("receptionist", "admin", "doctor", "nurse"))],
)
async def get_patient_photo_url(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    storage: StorageClient = Depends(get_storage),
) -> PhotoUrlOut:
    """Return a fresh 1-hour presigned GET URL for the patient's current photo."""
    patient = await db.get(Patient, patient_id)
    if not patient or patient.facility_id != current_db_user.facility_id or patient.deleted_at is not None:
        raise HTTPException(404, {"code": "patient_not_found"})
    if not patient.photo_file_id:
        raise HTTPException(404, {"code": "no_photo"})

    object_name = f"patients/{patient_id}/photo/{patient.photo_file_id}"
    if not await storage.object_exists(object_name):
        raise HTTPException(404, {"code": "photo_not_in_storage"})

    url = await storage.presign_get(object_name, expires_seconds=3600)
    return PhotoUrlOut(file_id=patient.photo_file_id, patient_id=patient_id, url=url)

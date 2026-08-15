"""files module router — endpoints land here; see this module's GitHub issues.

B7-W6-01: MinIO file APIs. Role lists below are unconfirmed -- best guess
(any staff role plausibly uploading/viewing a patient photo, ID proof, or
report), confirm before merge, same as consent's own role-list flags.
"""
import uuid

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.files import service
from app.files.schemas import FileDownloadUrlOut, FileOut

router = APIRouter(prefix="/files", tags=["files"])

_FILE_ROLES = ("receptionist", "nurse", "doctor", "lab_tech", "radiology_tech", "pharmacist", "admin")


def _extract_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


@router.get("/ping")
async def ping() -> dict:
    return {"module": "files", "status": "stub"}


@router.post(
    "/upload",
    response_model=FileOut,
    status_code=201,
    dependencies=[Depends(require_roles(*_FILE_ROLES))],
)
async def upload_file(
    request: Request,
    user: CurrentDbUser,
    upload: UploadFile,
    owner_module: str | None = Form(default=None),
    patient_id: uuid.UUID | None = Form(default=None),
    sensitivity: str = Form(default="normal"),
    db: AsyncSession = Depends(get_db),
) -> FileOut:
    record = await service.upload_file(
        db,
        upload=upload,
        facility_id=user.facility_id,
        uploaded_by=user.id,
        owner_module=owner_module,
        patient_id=patient_id,
        sensitivity=sensitivity,
        ip_address=_extract_ip(request),
    )
    return FileOut.model_validate(record)


@router.get(
    "/{file_id}",
    response_model=FileOut,
    dependencies=[Depends(require_roles(*_FILE_ROLES))],
)
async def get_file(
    file_id: uuid.UUID, request: Request, user: CurrentDbUser, db: AsyncSession = Depends(get_db)
) -> FileOut:
    record = await service.get_file_record(db, file_id, facility_id=user.facility_id)
    await service.record_view_access(db, file_id, user_id=user.id, ip_address=_extract_ip(request))
    return FileOut.model_validate(record)


@router.get(
    "/{file_id}/download-url",
    response_model=FileDownloadUrlOut,
    dependencies=[Depends(require_roles(*_FILE_ROLES))],
)
async def get_file_download_url(
    file_id: uuid.UUID, request: Request, user: CurrentDbUser, db: AsyncSession = Depends(get_db)
) -> FileDownloadUrlOut:
    url = await service.get_download_url(
        db, file_id, facility_id=user.facility_id, user_id=user.id, ip_address=_extract_ip(request)
    )
    return FileDownloadUrlOut(url=url, expires_in_seconds=service.PRESIGNED_URL_EXPIRY_SECONDS)

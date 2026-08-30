"""files module router — endpoints land here; see this module's GitHub issues.

B7-W6-01: MinIO file APIs. Role lists below are unconfirmed -- best guess
(any staff role plausibly uploading/viewing a patient photo, ID proof, or
report), confirm before merge, same as consent's own role-list flags.
"""
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.files import service
from app.files.schemas import FileDownloadUrlOut, FileEraseRequest, FileOut

router = APIRouter(prefix="/files", tags=["files"])

_FILE_ROLES = ("receptionist", "nurse", "doctor", "lab_tech", "radiology_tech", "pharmacist", "admin")


def _extract_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


# Module-liveness stub. Gated on `admin` for the same reason ot/, outbox/,
# blood_bank/, registration/ and security_audit/ already are: an
# unauthenticated endpoint on a health system is a finding regardless of
# payload, and the response still discloses which modules exist — useful
# reconnaissance, useless to a legitimate caller.
#
# Fourteen of these were still public after the WASA M4 pass closed five of
# them, so `make contract`-style module enumeration remained available to
# anyone who could reach the host. Nothing consumes them: no frontend call, no
# e2e script, no compose healthcheck (those probe Mongo and Redis directly),
# no Grafana panel.
@router.get("/ping", dependencies=[Depends(require_roles("admin"))])
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


@router.post(
    "/{file_id}/erase",
    response_model=FileOut,
    dependencies=[Depends(require_roles("admin"))],
)
async def erase_file(
    file_id: uuid.UUID,
    payload: FileEraseRequest,
    request: Request,
    user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> FileOut:
    """Destroy a file's contents under a data-protection request (#368).

    POST, not DELETE. The row is not deleted and never will be — DELETE would
    describe the wrong operation and would invite a client to expect 204 and an
    absent resource afterwards. What actually happens is a tombstone: the bytes
    go, the row and its access trail stay, and this returns the tombstone so the
    caller can see erased_at and the reason they just recorded.

    admin-only. Erasure is a data-controller decision, not clinical work, and
    the roles that may READ a file are deliberately not the roles that may
    destroy one.
    """
    try:
        record = await service.erase_file(
            db,
            file_id,
            facility_id=user.facility_id,
            user_id=user.id,
            reason=payload.reason,
            ip_address=_extract_ip(request),
        )
    except service.FileAlreadyErased:
        raise HTTPException(409, "File has already been erased") from None
    return FileOut.model_validate(record)

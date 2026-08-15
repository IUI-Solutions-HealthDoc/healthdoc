"""
Service functions for the files module.

Repo path: backend/app/files/service.py

B7-W6-01: MinIO file APIs -- upload/download, pre-signed URLs, metadata +
access log.

VALIDATION (§4A.4, "the presigned-URL XSS path") is the load-bearing part
of this file: allow-list by SNIFFED magic bytes, never the client-supplied
Content-Type or filename extension. An HTML file uploaded as "report.jpg"
and later served from a presigned URL is stored XSS against staff
sessions -- the sniff is what stops that, not a filename check.

MinIO upload happens BEFORE the Postgres insert, and the two are not
transactional with each other (different systems). If the DB insert fails
after a successful MinIO PUT, the object is orphaned in MinIO with no
FileRecord pointing at it -- a known, already-flagged gap (see
app/files/models.py's docstring: "No retention/cleanup path for orphaned
MinIO objects on delete"), not something this ticket fixes.

AUDIT: files.facility_id is a real, NOT NULL column (unlike consent_records),
so this COULD use listeners.py's automatic __audit_resource_type__ opt-in --
not done here. Wiring that up means editing app/audit/listeners.py's shared
AUDITABLE_MODULE_PREFIXES allowlist, a file this PR doesn't touch; uses the
same manual audited_mutation() path consent's service.py uses instead.

file_access_log is a SEPARATE table from audit_logs, and only upload goes
through audited_mutation() (an audit_logs row, matching every other
mutation in this codebase). view/download-url write ONLY a file_access_log
row -- reads don't get an audit_logs row anywhere else in this codebase
either (consent's access_log.py writes data_access_log, not audit_logs, for
the same reason).

NOT BUILT HERE, ON PURPOSE: log-even-on-a-later-403 for file_access_log.
consent's data_access_log needed that because a route could be rejected by
a dependency AFTER the log write was requested (denials matter for DPDP).
Every route here has exactly one gate (require_roles, first and only
dependency) -- there's no "logged the attempt, then something else 403'd"
window to protect against, so file_access_log rows are written inline,
same session, no separate SessionLocal/fallback-file machinery. Flagging
this as a deliberate scope cut, not an oversight, in case a future route
adds a second gate and reopens that gap.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
from datetime import timedelta

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.audit.service import audited_mutation
from app.common.config import get_settings
from app.common.enums import FileAction
from app.files.minio_client import ensure_bucket, get_minio_client
from app.files.models import FileAccessLog, FileRecord
from app.patients.models import Patient

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # §4A.4: matches nginx client_max_body_size
PRESIGNED_URL_EXPIRY_SECONDS = 300  # short-lived, per schema doc §7

# Sniffed magic bytes -> content_type. §4A.4's exact allow-list, in this
# order deliberately: DICOM's signature sits at offset 128, not 0, so it's
# checked separately from the three offset-0 signatures.
_SIGNATURES_AT_START: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"%PDF-": "application/pdf",
}
_DICOM_PREAMBLE_LEN = 128
_DICOM_MAGIC = b"DICM"


def sniff_content_type(data: bytes) -> str | None:
    """Returns the real content_type from the file's own bytes, or None
    if it doesn't match anything on the §4A.4 allow-list. Never trust
    the client-supplied Content-Type or filename extension for this --
    that's exactly the check an XSS-via-upload attack is designed to
    defeat."""
    for signature, content_type in _SIGNATURES_AT_START.items():
        if data.startswith(signature):
            return content_type
    if (
        len(data) >= _DICOM_PREAMBLE_LEN + len(_DICOM_MAGIC)
        and data[_DICOM_PREAMBLE_LEN:_DICOM_PREAMBLE_LEN + len(_DICOM_MAGIC)] == _DICOM_MAGIC
    ):
        return "application/dicom"
    return None


def _object_key(*, facility_id: uuid.UUID, owner_module: str | None, file_id: uuid.UUID, content_type: str) -> str:
    ext = {
        "image/jpeg": ".jpg", "image/png": ".png",
        "application/pdf": ".pdf", "application/dicom": ".dcm",
    }[content_type]
    return f"{facility_id}/{owner_module or 'general'}/{file_id}{ext}"


async def upload_file(
    db: AsyncSession,
    *,
    upload: UploadFile,
    facility_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    owner_module: str | None,
    patient_id: uuid.UUID | None,
    sensitivity: str,
    ip_address: str | None,
) -> FileRecord:
    data = await upload.read()
    if not data:
        raise HTTPException(422, "Empty file")
    if len(data) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(413, f"File exceeds the {MAX_FILE_SIZE_BYTES} byte limit")

    content_type = sniff_content_type(data)
    if content_type is None:
        raise HTTPException(
            422,
            "File content does not match an allowed type "
            "(image/jpeg, image/png, application/pdf, application/dicom)",
        )

    if patient_id is not None:
        # files.patient_id is a real FK (RESTRICT) -- without this check
        # a bad id surfaces as an unhandled IntegrityError/500, and a
        # valid patient from a DIFFERENT facility would be silently
        # linked (the FK alone can't express "same facility").
        #
        # A column-scoped select, not db.get(Patient, ...): a full ORM
        # load selects every mapped column, including row_version (from
        # Patient's Versioned mixin) -- which 0006_patients.py never
        # actually creates. That drift is in app/patients/, not this
        # module; selecting only what this check needs avoids it rather
        # than fixing someone else's migration.
        patient_row = (
            await db.execute(
                select(Patient.facility_id).where(Patient.id == patient_id)
            )
        ).first()
        if patient_row is None or patient_row.facility_id != facility_id:
            raise HTTPException(404, "Patient not found")

    sha256 = hashlib.sha256(data).hexdigest()
    file_id = uuid.uuid4()
    object_key = _object_key(
        facility_id=facility_id, owner_module=owner_module, file_id=file_id, content_type=content_type
    )
    bucket = get_settings().minio_bucket_files

    def _put() -> None:
        ensure_bucket(bucket)
        get_minio_client().put_object(
            bucket, object_key, io.BytesIO(data), length=len(data), content_type=content_type,
        )

    # Blocking MinIO SDK call -- off the event loop, see module docstring.
    await asyncio.to_thread(_put)

    async with audited_mutation(
        db,
        facility_id=facility_id,
        action=AuditAction.CREATE,
        resource_type="files",
        patient_id=patient_id,
    ) as audit:
        record = FileRecord(
            id=file_id,
            bucket=bucket,
            object_key=object_key,
            original_name=upload.filename,
            content_type=content_type,
            size_bytes=len(data),
            sha256=sha256,
            owner_module=owner_module,
            facility_id=facility_id,
            patient_id=patient_id,
            uploaded_by=uploaded_by,
            sensitivity=sensitivity,
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)

        audit.resource_id = record.id
        audit.new_value = {"content_type": content_type, "size_bytes": len(data), "sha256": sha256}

        db.add(
            FileAccessLog(
                file_id=record.id, user_id=uploaded_by, action=FileAction.UPLOAD.value,
                ip_address=ip_address,
            )
        )
        await db.flush()

    return record


async def get_file_record(db: AsyncSession, file_id: uuid.UUID, *, facility_id: uuid.UUID) -> FileRecord:
    record = await db.get(FileRecord, file_id)
    if record is None or record.facility_id != facility_id:
        # Same "don't leak a different facility's row exists" shape as
        # consent's get_consent_record -- 404 either way.
        raise HTTPException(404, "File not found")
    return record


async def record_view_access(
    db: AsyncSession, file_id: uuid.UUID, *, user_id: uuid.UUID, ip_address: str | None
) -> None:
    db.add(FileAccessLog(file_id=file_id, user_id=user_id, action=FileAction.VIEW.value, ip_address=ip_address))
    await db.flush()


async def get_download_url(
    db: AsyncSession, file_id: uuid.UUID, *, facility_id: uuid.UUID, user_id: uuid.UUID, ip_address: str | None
) -> str:
    record = await get_file_record(db, file_id, facility_id=facility_id)

    def _presign() -> str:
        return get_minio_client().presigned_get_object(
            record.bucket, record.object_key, expires=timedelta(seconds=PRESIGNED_URL_EXPIRY_SECONDS),
        )

    url = await asyncio.to_thread(_presign)

    db.add(FileAccessLog(file_id=file_id, user_id=user_id, action=FileAction.DOWNLOAD.value, ip_address=ip_address))
    await db.flush()

    return url

"""
Pydantic schemas for the files module.

Repo path: backend/app/files/schemas.py

B7-W6-01: MinIO file APIs. FileOut deliberately excludes bucket/object_key
-- schema doc §7: "never in any response: ... internal file object keys
(serve files via presigned URL endpoints)". A presigned URL is the only
sanctioned way a client ever reaches the actual bytes.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_name: str | None
    content_type: str | None
    size_bytes: int | None
    sha256: str
    owner_module: str | None
    facility_id: uuid.UUID
    patient_id: uuid.UUID | None
    uploaded_by: uuid.UUID
    sensitivity: str
    scan_status: str
    created_at: datetime
    updated_at: datetime


class FileDownloadUrlOut(BaseModel):
    url: str
    expires_in_seconds: int

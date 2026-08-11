"""
Pydantic response schemas for the audit query API (B7-W4-01).

Repo path: backend/app/audit/schemas.py

Field list matches docs/database-schema.md §4.4 exactly for `/audit/logs`:
id, user_id, role, action, resource_type, resource_id, patient_id,
old_value, new_value, created_at, entry_hash. Deliberately NOT the full
AuditLog row — chain_seq/prev_hash/signature/signer_key_id/sealed_at/
facility_id/department_id/visit_id/reason/ip_address/device_id are
internal-integrity or write-path fields the doc doesn't expose here.
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    role: str | None
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    patient_id: uuid.UUID | None
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    created_at: datetime
    entry_hash: str | None

    model_config = ConfigDict(from_attributes=True)


class AuditLogListOut(BaseModel):
    items: list[AuditLogOut]
    page: int
    page_size: int
    total: int

"""
Pydantic schemas for the consent module.

Repo path: backend/app/consent/schemas.py

Only what's needed to back the /patients/{patient_id}/records demo
route (proves out log_patient_data_access against a real endpoint).
Add ConsentPurpose/ConsentWithdrawal/etc. schemas here as those CRUD
endpoints get built — not scope-creeping into them from this ticket.

Field names mirror DB columns (snake_case) per schema doc §4.2.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConsentRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    visit_id: uuid.UUID | None
    purpose_id: uuid.UUID
    granted_by_type: str
    granted_by_user_id: uuid.UUID | None
    granted_at: datetime
    expires_at: datetime | None
    scope: list[str] | None
    channel: str
    status: str
    status_changed_at: datetime
    created_at: datetime
    updated_at: datetime

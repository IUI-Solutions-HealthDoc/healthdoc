"""
Pydantic schemas for the consent module.

Repo path: backend/app/consent/schemas.py

ConsentRecordOut backed the /patients/{patient_id}/records demo route
from the previous ticket. Everything else here is B7-W4-02 (Consent
CRUD: purpose/scope/channel, nullable expiry, status transitions).

Field names mirror DB columns (snake_case) per schema doc §4.2.
Enum-shaped fields (granted_by_type, channel, status,
withdrawn_by_type) are typed with the real CheckedEnum classes from
app.common.enums, not plain str — FastAPI/Pydantic then reject an
invalid value with a clean 422 at the boundary instead of relying
solely on the DB CHECK constraint to catch it after the fact.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.common.enums import ConsentChannel, ConsentStatus, GrantedByType


class ConsentRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    visit_id: uuid.UUID | None
    purpose_id: uuid.UUID
    granted_by_type: str
    granted_by_user_id: uuid.UUID | None
    guardian_name: str | None
    guardian_relationship: str | None
    granted_at: datetime
    expires_at: datetime | None
    scope: list[str] | None
    channel: str
    consent_artefact_id: str | None
    consent_artefact_signature: str | None
    status: str
    status_changed_at: datetime
    created_by: uuid.UUID
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ConsentPurposeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    purpose_code: str
    description: str | None
    default_expiry_days: int | None
    # Exposed but not yet READ by any service logic -- access_log.py's
    # consent_required is caller-supplied per route, not derived from
    # this. Works today; flagged so the two don't quietly drift apart.
    requires_explicit_consent: bool
    is_active: bool


class ConsentRecordCreate(BaseModel):
    purpose_id: uuid.UUID
    visit_id: uuid.UUID | None = None
    granted_by_type: GrantedByType
    granted_by_user_id: uuid.UUID | None = None
    guardian_name: str | None = None
    guardian_relationship: str | None = None
    expires_at: datetime | None = None  # nullable per issue spec
    scope: list[str] | None = None
    channel: ConsentChannel
    consent_artefact_id: str | None = None
    consent_artefact_signature: str | None = None
    # Only valid starting states -- 'requested' is for the abdm_consent_
    # manager async flow, every other channel grants immediately.
    status: Literal[ConsentStatus.GRANTED, ConsentStatus.REQUESTED] = ConsentStatus.GRANTED


class ConsentStatusTransitionIn(BaseModel):
    """requested -> granted/denied only; see service.py."""

    status: Literal[ConsentStatus.GRANTED, ConsentStatus.DENIED]
    reason: str | None = None


class ConsentWithdrawalCreate(BaseModel):
    # GrantedByType, not the wider DB CHECK -- 'system_expiry' is
    # reserved for the automated expiry sweep, not this manual endpoint.
    withdrawn_by_type: GrantedByType
    withdrawn_by_user_id: uuid.UUID | None = None
    reason: str | None = None


class ConsentWithdrawalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    consent_id: uuid.UUID
    withdrawn_by_type: str
    withdrawn_by_user_id: uuid.UUID | None
    withdrawn_at: datetime
    reason: str | None
    cascaded_actions: dict[str, str] | None
    cascade_deadline: datetime | None
    cascade_completed_at: datetime | None

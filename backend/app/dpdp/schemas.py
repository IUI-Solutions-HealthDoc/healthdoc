"""API contracts for DPO, grievance, and consent-manager workflows."""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.enums import GrievanceStatus, GrievanceType


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError("must not be blank")
    return normalized


_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?\d[\d ()-]{8,}\d)")


def _reachable(contact: str) -> bool:
    if _EMAIL.search(contact):
        return True
    return any(10 <= len(re.sub(r"\D", "", m)) <= 13 for m in _PHONE.findall(contact))


class DpoAppointmentCreate(BaseModel):
    user_id: uuid.UUID
    replaces_dpo_id: uuid.UUID | None = None
    contact_published: bool = False
    published_contact: str | None = Field(default=None, max_length=500)

    @field_validator("published_contact")
    @classmethod
    def strip_contact(cls, value: str | None) -> str | None:
        value = _strip(value)
        # The published contact is how a data principal reaches the DPO, so it
        # must carry an email address or a phone number; "abc" was accepted
        # (QA 12 Oct 2026).
        if value is not None and not _reachable(value):
            raise ValueError("published_contact must include an email address or a phone number")
        return value

    @model_validator(mode="after")
    def published_contact_must_match_flag(self):
        if self.contact_published and self.published_contact is None:
            raise ValueError("published_contact is required when contact_published is true")
        if not self.contact_published and self.published_contact is not None:
            raise ValueError("published_contact requires contact_published=true")
        return self


class DpoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    facility_id: uuid.UUID
    user_id: uuid.UUID
    appointed_at: datetime
    contact_published: bool
    published_contact: str | None
    is_active: bool
    created_by: uuid.UUID
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class GrievanceCreate(BaseModel):
    patient_id: uuid.UUID
    grievance_type: GrievanceType
    description: str = Field(min_length=1, max_length=10_000)
    due_at: datetime
    assigned_to: uuid.UUID | None = None

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return _strip(value)  # type: ignore[return-value]

    @field_validator("due_at")
    @classmethod
    def due_at_must_be_future(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("due_at must include a timezone")
        if value <= datetime.now(UTC):
            raise ValueError("due_at must be in the future")
        return value


class GrievanceTransition(BaseModel):
    status: GrievanceStatus
    resolution: str | None = Field(default=None, max_length=10_000)
    escalation_reason: str | None = Field(default=None, max_length=10_000)
    assigned_to: uuid.UUID | None = None

    @field_validator("resolution", "escalation_reason")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return _strip(value)


class GrievanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    grievance_number: str
    patient_id: uuid.UUID
    facility_id: uuid.UUID
    grievance_type: str
    description: str
    status: str
    assigned_to: uuid.UUID | None
    due_at: datetime
    resolution: str | None
    resolved_at: datetime | None
    escalation_reason: str | None
    created_by: uuid.UUID
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class GrievanceListOut(BaseModel):
    items: list[GrievanceOut]
    page: int
    page_size: int
    total: int


class ConsentManagerCreate(BaseModel):
    cm_registration_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=500)
    endpoint_url: AnyHttpUrl | None = None

    @field_validator("cm_registration_id", "name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _strip(value)  # type: ignore[return-value]


class ConsentManagerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    endpoint_url: AnyHttpUrl | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        return _strip(value)

    @model_validator(mode="after")
    def at_least_one_change(self):
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        if "is_active" in self.model_fields_set and self.is_active is None:
            raise ValueError("is_active cannot be null")
        return self


class ConsentManagerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cm_registration_id: str
    name: str
    endpoint_url: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

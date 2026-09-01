"""
backend/app/opd/schemas.py

Pydantic request/response models for the /visits endpoints.
Field names match DB columns exactly (schema doc §4.2 rule: JSON keys =
snake_case column names, no renaming layer).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class VisitCreate(BaseModel):
    patient_id: UUID

    #: Ignored. Both are taken from the authenticated user's token — see the
    #: router. Kept optional rather than removed so existing callers that still
    #: send them do not start failing validation; the router rejects a
    #: facility_id that disagrees with the caller's own.
    created_by: UUID | None = None
    facility_id: UUID | None = None

    department_id: UUID | None = None
    visit_type: str = Field(
        ..., description="opd | ipd | day_care | emergency | teleconsult"
    )
    visit_date: datetime


class VisitTypeUpdate(BaseModel):
    """Reclassify a visit — OPD escalated to IPD, IPD corrected to day care.

    `reason` is required, not optional. Changing what kind of episode of care a
    patient is having affects the bill, the bed count and the discharge
    expectation, and "who changed this and why" is the first question asked
    when a ward census does not reconcile.
    """

    visit_type: str = Field(..., description="opd | ipd | day_care | emergency | teleconsult")
    reason: str = Field(..., min_length=3, max_length=500)


class VisitOut(BaseModel):
    id: UUID
    visit_number: str
    patient_id: UUID
    facility_id: UUID
    department_id: UUID | None
    visit_type: str
    status: str
    visit_date: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VisitStatusUpdate(BaseModel):
    updated_by: UUID
    status: str = Field(
        ...,
        description=(
            "Target status: registered | in_consultation | completed | "
            "lwbs | cancelled"
        ),
    )
    reason: str | None = Field(
        default=None,
        description="Required when moving to lwbs or cancelled.",
    )

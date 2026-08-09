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
    created_by: UUID
    facility_id: UUID
    department_id: UUID | None = None
    visit_type: str = Field(
        ..., description="opd | ipd | emergency | teleconsult"
    )
    visit_date: datetime


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
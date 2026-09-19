"""Pydantic schemas for clinical terminology and specialty templates."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TerminologySearchItem(BaseModel):
    code: str
    title: str
    system: str  # icd10, icd11, snomed
    system_label: str
    category: str
    is_leaf: bool = True


class SpecialtyFieldOption(BaseModel):
    value: str
    label: str


class SpecialtyTemplateField(BaseModel):
    name: str
    label: str
    type: str  # number, text, select, multiselect, boolean, date, object
    required: bool = False
    options: list[SpecialtyFieldOption] | None = None
    unit: str | None = None
    help_text: str | None = None


class SpecialtyTemplateSection(BaseModel):
    title: str
    description: str | None = None
    fields: list[SpecialtyTemplateField]


class SpecialtyTemplateOut(BaseModel):
    specialty_type: str
    title: str
    description: str
    sections: list[SpecialtyTemplateSection]


class SpecialtyEncounterCreate(BaseModel):
    specialty_type: str = Field(..., description="Specialty identifier: pediatric, cardiology, obstetrics")
    clinical_data: dict[str, Any] = Field(default_factory=dict, description="Structured clinical findings")


class SpecialtyEncounterOut(BaseModel):
    id: uuid.UUID
    encounter_id: uuid.UUID
    patient_id: uuid.UUID
    specialty_type: str
    clinical_data: dict[str, Any]
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

"""Schemas for configurable forms, order sets, and CSV operations (HD-30)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class FormFieldOption(BaseModel):
    label: str
    value: str


class FormFieldDef(BaseModel):
    id: str
    label: str
    type: str = Field(description="text | number | select | checkbox | textarea | date")
    required: bool = False
    options: list[FormFieldOption] | None = None
    placeholder: str | None = None


class FormDefinitionCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    title: str = Field(..., min_length=2, max_length=150)
    version: int = Field(default=1, ge=1)
    status: str = Field(default="published", description="draft | published | retired")
    fields_schema: list[dict[str, Any]] = Field(default_factory=list)


class FormDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    title: str
    version: int
    status: str
    fields_schema: list[dict[str, Any]]
    created_by: uuid.UUID
    created_at: datetime


class FormSubmissionCreate(BaseModel):
    patient_id: uuid.UUID
    visit_id: uuid.UUID | None = None
    form_id: uuid.UUID
    form_data: dict[str, Any]


class FormSubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    visit_id: uuid.UUID | None
    form_id: uuid.UUID
    form_version: int
    form_data: dict[str, Any]
    submitted_by: uuid.UUID
    submitted_at: datetime
    created_at: datetime


class ClinicalOrderSetCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    title: str = Field(..., min_length=2, max_length=150)
    category: str = Field(default="general", max_length=50)
    orders: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True


class ClinicalOrderSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    title: str
    category: str
    orders: list[dict[str, Any]]
    is_active: bool
    created_at: datetime


class ApplyOrderSetRequest(BaseModel):
    patient_id: uuid.UUID
    visit_id: uuid.UUID


class ApplyOrderSetResult(BaseModel):
    order_set_code: str
    patient_id: uuid.UUID
    visit_id: uuid.UUID
    orders_applied: list[dict[str, Any]]
    message: str


class CsvValidateRequest(BaseModel):
    entity_type: str = Field(..., description="vaccines | forms | inventory")
    csv_content: str


class CsvValidationResult(BaseModel):
    valid: bool
    entity_type: str
    row_count: int
    columns: list[str]
    errors: list[str]
    warnings: list[str] = Field(default_factory=list)


class CsvImportRequest(BaseModel):
    entity_type: str = Field(..., description="vaccines | forms | inventory")
    csv_content: str


class CsvImportResult(BaseModel):
    entity_type: str
    imported_count: int
    message: str

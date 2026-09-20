"""Schemas for configurable forms, order sets, and CSV operations (HD-30)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FormFieldOption(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=200)


class FormFieldDef(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=200)
    type: Literal["text", "number", "select", "checkbox", "textarea", "date"]
    required: bool = False
    options: list[FormFieldOption] | None = None
    placeholder: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_options(self):
        if self.type == "select":
            if not self.options or len(self.options) > 100:
                raise ValueError("Select fields need between 1 and 100 options")
            values = [option.value for option in self.options]
            if len(set(values)) != len(values):
                raise ValueError("Option values must be unique")
        elif self.options:
            raise ValueError("Options are only supported for select fields")
        return self


class FormDefinitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(..., min_length=2, max_length=50)
    title: str = Field(..., min_length=2, max_length=150)
    version: int = Field(default=1, ge=1)
    status: Literal["draft", "published", "retired"] = "published"
    fields_schema: list[dict[str, Any]] = Field(min_length=1, max_length=100)

    @field_validator("fields_schema")
    @classmethod
    def validate_fields(cls, values):
        fields = [FormFieldDef.model_validate(field) for field in values]
        if len({field.id for field in fields}) != len(fields):
            raise ValueError("Form field IDs must be unique")
        return [field.model_dump(exclude_none=True) for field in fields]


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
    model_config = ConfigDict(extra="forbid")
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

"""
Request/response shapes for the radiology API (#203).
Mirrors pathology/schemas.py pattern - snake_case, id + accession_number both returned.
"""
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints


MachineId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]
RecordedReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)
]
ClinicalNarrative = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
]


class RadiologyOrderItemCreate(BaseModel):
    """Body for POST /radiology/order-items"""
    modality: str = Field(min_length=1, max_length=30)
    scan_type: str = Field(min_length=1, max_length=500)
    machine_id: MachineId | None = None


class RadiologyOrderItemOut(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    accession_number: str
    modality: str
    scan_type: str
    machine_id: str | None
    pacs_study_uid: str | None
    scheduled_at: datetime | None
    scan_completed_at: datetime | None = None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScheduleRequest(BaseModel):
    """Body for PUT /radiology/order-items/{item_id}/schedule"""
    scheduled_at: AwareDatetime
    machine_id: MachineId


class RescheduleRequest(ScheduleRequest):
    """Move a booked scan while retaining the reason in the audit trail."""
    reason: RecordedReason


class CancelScanRequest(BaseModel):
    """Cancel an unperformed scan; completed clinical work is immutable."""
    reason: RecordedReason


class ScanCompletionRequest(BaseModel):
    """Body for PUT /radiology/order-items/{item_id}/scan-complete"""
    completed_at: AwareDatetime | None = None


class RadiologyOrderItemListOut(BaseModel):
    items: list[RadiologyOrderItemOut]
    page: int
    page_size: int
    total: int


class RadiologyReportCreate(BaseModel):
    """Body for POST /radiology/order-items/{item_id}/reports (radiologist draft)."""
    findings: ClinicalNarrative
    impression: ClinicalNarrative
    pacs_study_uid: str | None = None


class RadiologyReportSignOff(BaseModel):
    """Body for PUT /radiology/order-items/{item_id}/reports/sign-off"""
    findings: ClinicalNarrative | None = None
    impression: ClinicalNarrative | None = None


class RadiologyReportHistoryOut(BaseModel):
    """Response for GET /radiology/order-items/{item_id}/reports.

    Mirrors pathology's LabResultHistoryOut. Radiology had no read endpoint at
    all: a radiologist could draft (POST) and sign off (PUT), but the ordering
    doctor had no way to read what was written except the FHIR bundle, which
    returns only the current version wrapped in a DiagnosticReport.

    All versions, newest first. The history is the clinically interesting part —
    a preliminary read that was revised on final is exactly what a treating
    doctor needs to see, and `is_current` alone cannot show that it changed.
    """

    items: list["RadiologyReportOut"]


class RadiologyReportOut(BaseModel):
    id: uuid.UUID
    radiology_order_item_id: uuid.UUID
    version: int
    is_current: bool
    findings: str
    impression: str
    status: str
    created_by: uuid.UUID
    created_at: datetime
    tat_minutes: int | None = None

    model_config = ConfigDict(from_attributes=True)

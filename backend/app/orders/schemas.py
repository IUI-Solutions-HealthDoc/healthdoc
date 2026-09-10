"""backend/app/orders/schemas.py -- request/response models for order creation. Field names match DB columns (schema doc §4.2)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class OrderCreate(BaseModel):
    encounter_id: UUID
    patient_id: UUID
    #: Ignored — the order is attributed to the authenticated caller. Optional
    #: rather than removed so existing callers keep validating; the router
    #: refuses a value that disagrees with the caller's own id.
    #:
    #: This was REQUIRED and was written straight through to orders.created_by,
    #: so any caller could file a lab test or scan under a colleague's name —
    #: while this module's own docstring said "created_by comes from
    #: current_db_user, never the request body".
    created_by: UUID | None = None
    order_type: str = Field(..., description="lab | radiology | pharmacy | procedure | blood")
    priority: str = Field(default="routine", description="routine | urgent | stat")
    ordered_at: datetime | None = None


class OrderOut(BaseModel):
    id: UUID
    order_number: str
    encounter_id: UUID
    patient_id: UUID
    facility_id: UUID
    order_type: str
    priority: str
    status: str
    # None means an old idempotency snapshot predating this field. Clients
    # must re-read the order, never guess that a missing mode is internal.
    fulfilment_mode: Literal["internal", "external_referral"] | None = None
    completed_at: datetime | None = None
    ordered_at: datetime
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class OrderListOut(BaseModel):
    items: list[OrderOut]


class ExternalReferralOut(OrderOut):
    patient_name: str
    patient_identifier: str | None
    visit_number: str
    result_count: int
    last_received_at: datetime | None


class ExternalReferralListOut(BaseModel):
    items: list[ExternalReferralOut]
    total: int
    limit: int
    offset: int


class ExternalResultCreate(BaseModel):
    provider_name: str | None = Field(default=None, max_length=500)
    summary: str = Field(min_length=1, max_length=10_000)
    result_file_id: UUID | None = None
    observed_on: date | None = None

    @field_validator("provider_name", "summary")
    @classmethod
    def strip_non_blank_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("observed_on")
    @classmethod
    def observed_date_cannot_be_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("observed_on cannot be in the future")
        return value


class ExternalResultOut(BaseModel):
    id: UUID
    order_id: UUID
    provider_name: str | None
    summary: str
    result_file_id: UUID | None
    observed_on: date | None
    recorded_by: UUID
    recorded_at: datetime
    created_at: datetime
    model_config = {"from_attributes": True}


class ExternalResultListOut(BaseModel):
    items: list[ExternalResultOut]


class PrescriptionItemCreate(BaseModel):
    medicine_item_id: UUID | None = None
    medicine_name: str
    dosage: str | None = None
    frequency: str | None = None
    duration_days: int | None = None
    route: str | None = None
    instructions: str | None = None
    #: Required when a retry is needed after the first save came back
    #: with an allergy conflict (app.allergies.service.AllergyConflict).
    #: Ignored if there was no conflict. Anaphylaxis can never be
    #: overridden regardless of what's passed here.
    override_reason: str | None = None


class PrescriptionCreate(BaseModel):
    encounter_id: UUID
    notes: str | None = None
    items: list[PrescriptionItemCreate]


class PrescriptionItemOut(BaseModel):
    id: UUID
    prescription_id: UUID
    medicine_item_id: UUID | None
    medicine_name: str
    dosage: str | None
    frequency: str | None
    duration_days: int | None
    route: str | None
    instructions: str | None
    status: str
    allergy_override_reason: str | None
    allergy_override_by: UUID | None
    model_config = {"from_attributes": True}


class PrescriptionOut(BaseModel):
    id: UUID
    encounter_id: UUID
    facility_id: UUID
    patient_id: UUID
    notes: str | None
    created_at: datetime
    updated_at: datetime
    items: list[PrescriptionItemOut]
    #: Non-blocking. A rule-based interaction match among the ingredients
    #: on this prescription -- unlike an allergy conflict, this never
    #: prevents the save; it's surfaced so the clinician can review.
    interaction_warnings: list[str] = []
    model_config = {"from_attributes": True}


class ResultWorklistItemOut(BaseModel):
    """One lab or radiology order item on a doctor's results worklist.

    `encounter_id` is carried deliberately: doctor_reviews belong to an
    encounter, so a screen that opens a review from this list needs it. The
    frontend fixture omitted it, which is why its review lifecycle had to file
    everything against one hardcoded encounter id.

    `result_status` and `reported_at` are null until a result exists — that is
    "ordered, not back yet", which is the state most of this list is in.
    `review_status` is null until a review is opened.
    """

    id: UUID
    order_type: str
    order_id: UUID
    order_number: str
    encounter_id: UUID
    patient_id: UUID
    patient_name: str
    uhid: str | None
    accession_number: str
    test_name: str
    modality: str | None
    priority: str
    status: str
    result_status: str | None
    reported_at: datetime | None
    review_status: str | None


class ResultWorklistOut(BaseModel):
    items: list[ResultWorklistItemOut]

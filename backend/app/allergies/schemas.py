"""backend/app/allergies/schemas.py -- /allergies request/response models.

recorded_by and verified_by come from current_db_user, never the request body
(same rule as encounters/router.py and opd/router.py).

Enum-valued fields are typed `str` and validated against the CheckedEnum's
`.values()` rather than hardcoded — a literal list here is exactly how the doc
and the code drift apart, which spec_check.py exists to catch.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.enums import AllergenType, AllergySeverity, AllergyStatus


def _one_of(enum_cls: type) -> str:
    return " | ".join(sorted(enum_cls.values()))


class AllergyCreate(BaseModel):
    patient_id: UUID
    allergen_type: str = Field(..., description=_one_of(AllergenType))
    substance_text: str = Field(
        ..., min_length=1,
        description="Always required, even when coded. 'penicillin injection' from an "
                    "attendant is the whole record in a rural OPD and must not be lost "
                    "to a failed lookup.",
    )
    ingredient_code: str | None = Field(
        default=None,
        description="The matchable key. NULL means display-only: shown in the banner, "
                    "can never block a prescription.",
    )
    inventory_item_id: UUID | None = None
    reaction: str | None = None
    severity: str = Field(..., description=_one_of(AllergySeverity))
    onset_date: date | None = None

    @field_validator("allergen_type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        if v not in AllergenType.values():
            raise ValueError(f"allergen_type must be one of: {_one_of(AllergenType)}")
        return v

    @field_validator("severity")
    @classmethod
    def _valid_severity(cls, v: str) -> str:
        if v not in AllergySeverity.values():
            raise ValueError(f"severity must be one of: {_one_of(AllergySeverity)}")
        return v


class AllergyStatusUpdate(BaseModel):
    """Allergy records are corrected, never deleted.

    There is no DELETE endpoint by design: a removed allergy that was real is the
    failure mode the status enum exists to prevent. Use `refuted` when it has been
    clinically ruled out and `entered_in_error` for a typo or wrong patient.
    """

    status: str = Field(..., description=_one_of(AllergyStatus))
    row_version: int = Field(
        ..., ge=1,
        description="The row_version you read. Rejected with 409 if it has moved, so "
                    "two clinicians cannot silently overwrite each other.",
    )

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        if v not in AllergyStatus.values():
            raise ValueError(f"status must be one of: {_one_of(AllergyStatus)}")
        return v


class AllergyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    allergen_type: str
    substance_text: str
    ingredient_code: str | None
    inventory_item_id: UUID | None
    reaction: str | None
    severity: str
    status: str
    onset_date: date | None
    recorded_by: UUID
    verified_by: UUID | None
    verified_at: datetime | None
    row_version: int
    created_at: datetime

    #: Coded AND active. The UI needs this to distinguish "checked and clear" from
    #: "could not check" — an uncoded allergy is real but unmatchable.
    is_blocking: bool
    #: Anaphylaxis. Never overridable, by any role.
    is_absolute: bool

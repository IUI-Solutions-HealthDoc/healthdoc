"""Patient request/response schemas — POST /patients (§4.4)."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.enums import Sex


def _normalise_aadhaar(value: str | None) -> str | None:
    """Return the 12 digits accepted by the blind-index function.

    Formatting spaces and hyphens are harmless and common on paper forms. Any
    other character, or a non-12-digit value, is rejected by Pydantic so it
    cannot become the ValueError/HTTP 500 found by authenticated ZAP.
    """
    if value is None:
        return None
    if any(not (character.isdigit() or character in " -") for character in value):
        raise ValueError("aadhaar_number may contain only digits, spaces and hyphens")
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) != 12:
        raise ValueError("aadhaar_number must contain exactly 12 digits")
    return digits


def _normalise_mobile(value: str | None) -> str | None:
    """Return a mobile as +91XXXXXXXXXX, or reject it.

    The field had NO validation at all, so a patient could be registered with
    a mobile of "00", "abc" or "!!!" — reported by manual testing, and worse
    than cosmetic: a mobile is how a hospital reaches a patient about a
    critical result, and an unreachable number discovered at that moment is
    the whole cost of not checking here.

    THE +91 IS ADDED, NOT DEMANDED. Front-desk staff type the ten digits they
    read off a form; requiring a country code is a rule the counter will lose
    to every time. Spaces, hyphens and a leading 0 or +91 are all accepted and
    normalised away, so one stored format comes out of many typed ones.

    What is NOT accepted: anything that is not an Indian mobile. The first
    digit must be 6-9 — Indian mobile numbering does not issue below that, so
    "0000000000" and "1234567890" are not numbers anyone can be called on.
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None

    if any(ch not in "0123456789+- " for ch in raw):
        raise ValueError(
            "mobile may contain only digits, spaces, hyphens and a leading +"
        )

    digits = "".join(ch for ch in raw if ch.isdigit())
    # Strip the country code or a trunk prefix if the caller supplied one.
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 10:
        raise ValueError("mobile must be a 10-digit Indian mobile number")
    if digits[0] not in "6789":
        raise ValueError("an Indian mobile number starts with 6, 7, 8 or 9")
    return f"+91{digits}"


def _normalise_abha(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if any(not (character.isdigit() or character in " -") for character in raw):
        raise ValueError("abha_number may contain only digits, spaces and hyphens")
    digits = "".join(character for character in raw if character.isdigit())
    if len(digits) != 14:
        raise ValueError("abha_number must contain exactly 14 digits")
    return digits


_UHID_SHAPE = re.compile(r"^IN-[A-Z]{2}-[A-Z0-9_]{1,20}-\d{4}-\d{6,}-\d$")


def _normalise_uhid(value: str | None) -> str | None:
    if value is None:
        return None
    normalised = value.strip().upper()
    if not normalised:
        return None
    if not _UHID_SHAPE.fullmatch(normalised):
        raise ValueError("uhid must use the format IN-STATE-FACILITY-YEAR-SEQUENCE-CHECKDIGIT")
    # Local import avoids making schemas and service import each other while
    # still applying the same check-digit algorithm used by the generator.
    from app.patients.service import validate_uhid

    if not validate_uhid(normalised):
        raise ValueError("uhid check digit is invalid")
    return normalised


def _validate_full_name(value: str | None) -> str | None:
    """A person's name, not a free-text field.

    Reported: full names containing digits were accepted and saved. A name is
    matched against government identity documents during ABHA linking and
    printed on discharge paperwork, so "Ram7" is not a harmless typo — it is a
    record that will fail to match later, at a point where nobody remembers
    typing it.

    Deliberately permissive about SHAPE while strict about digits: apostrophes,
    hyphens, full stops and non-Latin scripts are all real in Indian names, and
    a stricter pattern would reject more real patients than bad data. Digits
    and the characters used in injection payloads are what this refuses.
    """
    if value is None:
        return None
    name = " ".join(value.split())
    if not name:
        raise ValueError("full_name is required")
    if any(ch.isdigit() for ch in name):
        raise ValueError("full_name may not contain digits")
    if any(ch in "<>{}[]|\\^~`@#$%*_=+;" for ch in name):
        raise ValueError("full_name contains characters that are not part of a name")
    return name


class PatientCreate(BaseModel):
    full_name: str
    sex: Sex
    dob: date | None = None
    age_years: int | None = None
    mobile: str | None = None
    abha_number: str | None = None
    aadhaar_number: str | None = None

    _validate_aadhaar = field_validator("aadhaar_number")(_normalise_aadhaar)
    _validate_mobile = field_validator("mobile")(_normalise_mobile)
    _validate_abha = field_validator("abha_number")(_normalise_abha)
    _validate_name = field_validator("full_name")(_validate_full_name)

    @model_validator(mode="after")
    def _dob_or_age_required(self) -> PatientCreate:
        if (self.dob is None) == (self.age_years is None):
            raise ValueError("Exactly one of dob or age_years is required")
        return self


class PatientUpdate(BaseModel):
    """PATCH /patients/{id} — all fields optional, only supplied fields written.

    `reason` is not stored on the patient row — it is forwarded to the
    audit log's `reason` column so reviewers know WHY a field changed,
    not just what changed (schema doc §26.1 Audit Events).
    """
    full_name: str | None = None
    sex: Sex | None = None
    dob: date | None = None
    age_years: int | None = None
    mobile: str | None = None
    abha_number: str | None = None
    guardian_name: str | None = None
    guardian_relationship: str | None = None
    address_line: str | None = None
    village_town: str | None = None
    district: str | None = None
    state_code: str | None = None
    pincode: str | None = None
    reason: str | None = None  # audit reason, not stored on patient row

    # PATCH must enforce the same rules as POST. A validator on create
    # alone is a rule you can walk around by registering cleanly and then
    # editing — which is the more likely path for bad data anyway, since
    # corrections are where people paste.
    _validate_mobile = field_validator("mobile")(_normalise_mobile)
    _validate_abha = field_validator("abha_number")(_normalise_abha)
    _validate_name = field_validator("full_name")(_validate_full_name)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> PatientUpdate:
        updateable = (
            "full_name", "sex", "dob", "age_years", "mobile", "abha_number",
            "guardian_name", "guardian_relationship",
            "address_line", "village_town", "district", "state_code", "pincode",
        )
        if not any(getattr(self, f) is not None for f in updateable):
            raise ValueError("At least one patient field must be supplied for update")
        if self.dob is not None and self.age_years is not None:
            raise ValueError("dob and age_years cannot both be supplied")
        return self


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    uhid: str | None
    thid: str | None
    full_name: str
    sex: str
    dob: date | None
    age_years: int | None
    mobile: str | None
    abha_number: str | None
    identity_path: str
    identity_status: str
    photo_file_id: uuid.UUID | None
    facility_id: uuid.UUID
    created_at: datetime


class PatientDetailOut(PatientOut):
    """PatientOut plus the fields a single-record read needs.

    Kept separate rather than widening PatientOut, which is the response for
    POST and PATCH and is consumed by the registration flow — this is additive
    where it is wanted and unchanged where it is not.

    `row_version` is here because PATCH /patients/{id} increments it for
    optimistic concurrency (0035) and the If-Match check is staged as a
    follow-up. When that lands, the client needs a way to have read the value
    first; without a GET there was none.

    `merged_from_patient_id` is set when the caller asked for an id that has
    since been merged away. The body describes the surviving record, and this
    field says which id was asked for — otherwise a screen would silently show
    a different patient than the one requested.
    """

    status: str
    merged_into_patient_id: uuid.UUID | None = None
    merged_from_patient_id: uuid.UUID | None = None
    row_version: int


class PatientSearchRequest(BaseModel):
    full_name: str | None = None
    dob: date | None = None
    mobile: str | None = None
    uhid: str | None = None
    aadhaar_number: str | None = None
    abha_number: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    _validate_aadhaar = field_validator("aadhaar_number")(_normalise_aadhaar)
    _validate_mobile = field_validator("mobile")(_normalise_mobile)
    _validate_abha = field_validator("abha_number")(_normalise_abha)
    _validate_uhid = field_validator("uhid")(_normalise_uhid)
    _validate_name = field_validator("full_name")(_validate_full_name)

    @model_validator(mode="after")
    def _at_least_one_criterion(self) -> PatientSearchRequest:
        if not any([self.full_name, self.mobile, self.uhid, self.aadhaar_number, self.abha_number]):
            raise ValueError("At least one search criterion is required")
        if self.full_name and self.dob is None:
            raise ValueError("dob is required when searching by full_name")
        return self


class PatientSearchResult(BaseModel):
    id: uuid.UUID
    uhid: str | None
    full_name: str
    sex: str
    age_years: int | None
    mobile_masked: str | None
    match_score: float
    matched_on: str  # "aadhaar" | "abha" | "uhid" | "mobile" | "name_dob"


class PatientSearchResponse(BaseModel):
    items: list[PatientSearchResult]
    page: int
    page_size: int
    total: int

class MergeRequestCreate(BaseModel):
    source_patient_id: uuid.UUID
    target_patient_id: uuid.UUID
    source_type: str  # "thid" | "duplicate_uhid" (MergeSourceType enum)
    reason: str | None = None


class MergeActionRequest(BaseModel):
    reason: str | None = None  # required for reject, optional for approve


class MergeLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: str
    source_patient_id: uuid.UUID
    target_patient_id: uuid.UUID
    requested_by: uuid.UUID
    requested_at: datetime
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    status: str
    reason: str | None
    decision_reason: str | None = None

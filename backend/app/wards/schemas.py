"""wards module schemas."""
import uuid
from datetime import datetime

from pydantic import BaseModel


class WardOut(BaseModel):
    id: uuid.UUID
    name: str
    name_hi: str | None = None
    department_id: uuid.UUID | None
    facility_id: uuid.UUID
    is_active: bool

    model_config = {"from_attributes": True}


class BedOccupantOut(BaseModel):
    admission_id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str | None
    uhid: str | None
    admitted_at: datetime


class BedGridItemOut(BaseModel):
    bed_id: uuid.UUID
    bed_number: str
    status: str
    occupant: BedOccupantOut | None


class BedGridOut(BaseModel):
    ward_id: uuid.UUID
    items: list[BedGridItemOut]


class BedMismatchOut(BaseModel):
    """One disagreement between beds.status and the admissions table.

    admissions is authoritative; beds.status is a denormalised mirror kept in
    the same transaction. They can still drift — a crash between the two
    writes, or a manual UPDATE during support — and the ward only finds out
    when a nurse cannot admit into a bed that is visibly empty.
    """

    bed_id: uuid.UUID
    ward_id: uuid.UUID
    bed_status: str
    active_admission_id: uuid.UUID | None
    issue: str


class BedReconciliationOut(BaseModel):
    """Read-only: reports drift, never repairs it.

    Auto-correcting would mean guessing which side is wrong, and the wrong
    guess either marks an occupied bed free for a second admission or evicts a
    patient from the bed board. A human decides.
    """

    facility_id: uuid.UUID
    mismatch_count: int
    mismatches: list[BedMismatchOut]

"""wards module schemas."""
import uuid
from datetime import datetime
from pydantic import BaseModel


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

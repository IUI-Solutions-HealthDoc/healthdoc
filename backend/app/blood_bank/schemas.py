"""Pydantic schemas for the blood_bank module."""
import uuid
from datetime import date, datetime
from pydantic import BaseModel


class BloodDonorOut(BaseModel):
    id: uuid.UUID
    full_name: str
    sex: str | None
    blood_group: str
    mobile: str | None
    hemoglobin_g_dl: float | None
    last_donation_date: date | None
    next_eligible_date: date | None
    is_eligible: bool
    created_at: datetime

    class Config:
        from_attributes = True


class BloodUnitOut(BaseModel):
    id: uuid.UUID
    donor_id: uuid.UUID
    bag_number: str
    blood_group: str
    volume_ml: int
    expiry_date: date
    screening_status: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

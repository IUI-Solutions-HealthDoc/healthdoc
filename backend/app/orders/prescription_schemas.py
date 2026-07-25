import uuid
from typing import Optional
from pydantic import BaseModel, ConfigDict


class PrescriptionItemCreate(BaseModel):
    medicine_name: str
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration_days: Optional[int] = None
    route: Optional[str] = None
    instructions: Optional[str] = None


class PrescriptionCreate(BaseModel):
    encounter_id: uuid.UUID
    patient_id: uuid.UUID
    created_by: uuid.UUID
    notes: Optional[str] = None
    items: list[PrescriptionItemCreate]


class PrescriptionItemOut(BaseModel):
    id: uuid.UUID
    medicine_name: str
    dosage: Optional[str]
    frequency: Optional[str]
    duration_days: Optional[int]
    route: Optional[str]
    instructions: Optional[str]
    status: str

    model_config = ConfigDict(from_attributes=True)


class PrescriptionOut(BaseModel):
    id: uuid.UUID
    encounter_id: uuid.UUID
    patient_id: uuid.UUID
    notes: Optional[str]
    items: list[PrescriptionItemOut]

    model_config = ConfigDict(from_attributes=True)

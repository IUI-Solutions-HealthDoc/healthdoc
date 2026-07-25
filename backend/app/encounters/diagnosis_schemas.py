import uuid
from typing import Optional
from pydantic import BaseModel, ConfigDict


class DiagnosisCreate(BaseModel):
    encounter_id: uuid.UUID
    created_by: uuid.UUID
    icd_code: str
    icd_version: str
    icd_code_id: Optional[uuid.UUID] = None
    diagnosis_text: str
    diagnosis_type: str
    is_primary: bool = False


class DiagnosisOut(BaseModel):
    id: uuid.UUID
    encounter_id: uuid.UUID
    icd_code: str
    icd_version: str
    diagnosis_text: str
    diagnosis_type: str
    is_primary: bool

    model_config = ConfigDict(from_attributes=True)


class IcdSearchResult(BaseModel):
    code: str
    title: str
    icd_uri: Optional[str]
    is_postcoordinable: bool
    version: str

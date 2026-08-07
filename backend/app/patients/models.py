"""Patient model — schema doc §3-0006. Minimal fields needed for
visit/encounter FK resolution and tests on this branch; full
patient_identifiers, merge-log, and encrypted-identifier columns are
out of scope here (owned by B2, migration 0006).
"""
import uuid
from datetime import date

from sqlalchemy import CheckConstraint, Column, Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.common.db import Base
from app.common.models import UUIDPk, Timestamps, Blame


class Patient(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "patients"
    __table_args__ = (
        CheckConstraint(
            "dob IS NOT NULL OR age_years IS NOT NULL",
            name="ck_patients_dob_or_age",
        ),
        CheckConstraint(
            "uhid IS NOT NULL OR thid IS NOT NULL",
            name="ck_patients_has_identifier",
        ),
    )

    uhid = Column(String(30), unique=True, nullable=True)
    thid = Column(String(25), unique=True, nullable=True)
    full_name = Column(Text, nullable=False)
    sex = Column(String(30), nullable=False)
    dob = Column(Date, nullable=True)
    age_years = Column(Integer, nullable=True)
    identity_path = Column(String(30), nullable=False)
    identity_status = Column(String(30), nullable=False, default="verified")
    status = Column(String(30), nullable=False, default="active")
    facility_id = Column(
        UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False, index=True
    )

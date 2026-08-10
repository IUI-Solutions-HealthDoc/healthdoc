from sqlalchemy import Column, String, Text, Integer, Numeric, Date, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.common.models import UUIDPk, Timestamps, Blame
from app.common.db import Base


class BloodDonor(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "blood_donors"

    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"),
                         nullable=True, index=True)
    full_name = Column(Text, nullable=False)
    sex = Column(String(50), nullable=True)  # enum-backed: §3 blanket rule
    dob = Column(Date, nullable=True)
    age_years = Column(Integer, nullable=True)
    blood_group = Column(String(50), nullable=False)  # enum-backed: §3 blanket rule
    mobile = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)
    weight_kg = Column(Numeric(5, 2), nullable=True)
    hemoglobin_g_dl = Column(Numeric(4, 1), nullable=True)
    last_donation_date = Column(Date, nullable=True)
    next_eligible_date = Column(Date, nullable=True)
    is_eligible = Column(Boolean, nullable=False, server_default="false")
    remarks = Column(Text, nullable=True)


class BloodUnit(Base, UUIDPk, Timestamps):
    __tablename__ = "blood_units"

    donor_id = Column(UUID(as_uuid=True), ForeignKey("blood_donors.id", ondelete="RESTRICT"),
                       nullable=False, index=True)
    bag_number = Column(String(30), unique=True, nullable=False)
    blood_group = Column(String(50), nullable=False)  # enum-backed: §3 blanket rule
    volume_ml = Column(Integer, nullable=False)
    collected_at = Column(DateTime(timezone=True), nullable=True)
    expiry_date = Column(Date, nullable=False)
    screening_status = Column(String(50), nullable=False, server_default="pending")
    status = Column(String(50), nullable=False, server_default="available")

    issued_to_patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"),
                                   nullable=True, index=True)

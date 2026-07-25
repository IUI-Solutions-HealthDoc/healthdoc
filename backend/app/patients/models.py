"""SQLAlchemy model for `patients` (migration 0006). Previously missing —
no ORM model existed for this table anywhere, which meant any FK from
another table to patients.id (orders, prescriptions, visits, ...) would
raise NoReferencedTableError the moment SQLAlchemy tried to flush,
since the table wasn't registered on Base.metadata.
"""
from sqlalchemy import Column, ForeignKey, String, Text, Date, DateTime, SmallInteger
from sqlalchemy.dialects.postgresql import UUID

from app.common.db import Base
from app.common.models import Blame, Timestamps, UUIDPk


class Patient(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "patients"

    uhid = Column(String(30), nullable=True)
    thid = Column(String(25), nullable=True)
    full_name = Column(Text, nullable=False)
    sex = Column(String(50), nullable=False)
    dob = Column(Date, nullable=True)
    age_years = Column(SmallInteger, nullable=True)
    guardian_name = Column(Text, nullable=True)
    guardian_relationship = Column(String(50), nullable=True)
    mobile = Column(String(20), nullable=True)
    address_line = Column(Text, nullable=True)
    village_town = Column(Text, nullable=True)
    district = Column(Text, nullable=True)
    state_code = Column(String(5), nullable=True)
    pincode = Column(String(6), nullable=True)
    photo_file_id = Column(UUID(as_uuid=True), nullable=True)
    abha_number = Column(String(17), nullable=True)
    identity_path = Column(String(50), nullable=False)
    identity_status = Column(String(50), nullable=False, server_default="verified")
    status = Column(String(50), nullable=False, server_default="active")
    merged_into_patient_id = Column(UUID(as_uuid=True), nullable=True)
    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

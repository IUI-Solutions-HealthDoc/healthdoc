"""
backend/app/opd/models.py

SQLAlchemy models for the OPD module: visits (0007), encounters (0007),
icd_codes (0007), diagnoses (0007). Schema doc §3.
"""
from sqlalchemy import Column, ForeignKey, String, Text, DateTime, Boolean, CheckConstraint, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.common.db import Base


class Visit(Base):
    __tablename__ = "visits"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.uuid_generate_v4(),
    )
    visit_number = Column(String(30), unique=True, nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True)
    visit_type = Column(String(30), nullable=False)
    status = Column(String(30), nullable=False, server_default="registered")
    visit_date = Column(DateTime(timezone=True), nullable=False)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "visit_type IN ('opd', 'ipd', 'emergency', 'teleconsult')",
            name="ck_visits_visit_type",
        ),
        CheckConstraint(
            "status IN ('registered', 'in_consultation', 'completed', "
            "'lwbs', 'cancelled')",
            name="ck_visits_status",
        ),
    )


class Encounter(Base):
    __tablename__ = "encounters"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.uuid_generate_v4(),
    )
    visit_id = Column(UUID(as_uuid=True), ForeignKey("visits.id"), nullable=False)
    provider_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    encounter_type = Column(String(30), nullable=True)
    chief_complaint = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    # SOAP note (0018)
    subjective = Column(Text, nullable=True)
    objective = Column(Text, nullable=True)
    assessment = Column(Text, nullable=True)
    plan = Column(Text, nullable=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IcdCode(Base):
    __tablename__ = "icd_codes"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.uuid_generate_v4(),
    )
    version = Column(String(30), nullable=False)
    code = Column(String(30), nullable=False)
    title = Column(Text, nullable=False)
    icd_uri = Column(Text, nullable=True)
    is_postcoordinable = Column(Boolean, nullable=False, server_default="false")
    is_active = Column(Boolean, nullable=False, server_default="true")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.uuid_generate_v4(),
    )
    encounter_id = Column(UUID(as_uuid=True), ForeignKey("encounters.id"), nullable=False)
    icd_code = Column(String(30), nullable=False)
    icd_version = Column(String(30), nullable=False)
    icd_code_id = Column(UUID(as_uuid=True), ForeignKey("icd_codes.id"), nullable=True)
    icd_uri = Column(Text, nullable=True)
    post_coordinated_code = Column(Text, nullable=True)
    diagnosis_text = Column(Text, nullable=False)
    diagnosis_type = Column(String(30), nullable=False)
    is_primary = Column(Boolean, nullable=False, server_default="false")

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

class Vitals(Base):
    __tablename__ = "vitals"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.uuid_generate_v4(),
    )
    encounter_id = Column(UUID(as_uuid=True), ForeignKey("encounters.id"), nullable=False)
    bp_systolic = Column(Integer, nullable=True)
    bp_diastolic = Column(Integer, nullable=True)
    pulse = Column(Integer, nullable=True)
    temperature = Column(Numeric(4, 1), nullable=True)
    spo2 = Column(Integer, nullable=True)
    respiratory_rate = Column(Integer, nullable=True)
    weight = Column(Numeric(5, 2), nullable=True)
    height = Column(Numeric(5, 2), nullable=True)
    recorded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    recorded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "spo2 IS NULL OR (spo2 >= 0 AND spo2 <= 100)",
            name="ck_vitals_spo2_range",
        ),
    )

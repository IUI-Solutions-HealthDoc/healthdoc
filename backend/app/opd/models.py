"""
backend/app/opd/models.py

SQLAlchemy models for the OPD module: visits (0007), encounters (0007),
icd_codes (0007), diagnoses (0007). Schema doc §3.

Changes in this revision:
  - Visit now uses UUIDPk/Timestamps/Blame mixins instead of hand-rolled
    columns (per app/common/models.py: "Use these; never hand-roll
    id/timestamps").
  - Visit gains row_version (§4A.2 -- required on every mutable
    clinical/financial row; was only on Encounter before).
  - Visit.status CHECK now includes 'closed' (§4A.5 auto-close job
    sets this on a consulted-but-not-closed visit at end of business
    day; the old CHECK would have rejected that write).
  - Added ix_visits_patient_id_visit_date, ix_encounters_visit_id,
    ix_encounters_provider_user_id (required per §3, missing before).
  - VisitNumberCounter: fixed PK (was composite (facility_id,
    counter_date), which violates §1 rule 1 -- every table's PK is
    id UUID, no exceptions). Now id UUID PK + UNIQUE constraint,
    matching the queue_counters/billing_counters pattern in §3.
    Also removed the incorrect "migration 0025" reference -- real
    migration 0025 is staff_certifications/staff_training_records/
    kpi_snapshots (HR/KPI), not visit numbering. This table needs
    its own migration number; pick the next free one in your chain
    and update both the docstring and the actual migration file.

NOTE: the Vitals class that previously appeared at the bottom of this
file (with its own `from app.common.models import UUIDPk, Timestamps,
Blame` import) has been removed here -- it belongs to a different
module (nursing/vitals, migration 0023), not OPD, and looked like it
got concatenated in from a separate `cat` output. If it's genuinely
missing from wherever it should live, that's a separate fix.
"""
from sqlalchemy import (
    Column,
    ForeignKey,
    String,
    Text,
    DateTime,
    Boolean,
    CheckConstraint,
    Integer,
    Numeric,
    Date,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.common.db import Base
from app.common.models import UUIDPk, Timestamps, Blame


class VisitNumberCounter(Base, UUIDPk, Timestamps):
    """
    Gapless per-facility-per-business-day allocator for visit_number,
    same pattern as queue_counters (0009) and billing_counters (0014).

    TODO: this table has no home in the §3 migration map yet -- it was
    previously mis-cited as "0025" (that number belongs to HR/KPI).
    Create a real migration for it (next free number in your chain,
    coordinate with the team channel per §2) and update this
    docstring to match.
    """
    __tablename__ = "visit_number_counters"
    __table_args__ = (
        UniqueConstraint(
            "facility_id", "counter_date", name="uq_visit_number_counters_facility_id_counter_date"
        ),
    )

    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    counter_date = Column(Date, nullable=False)
    seq = Column(Integer, nullable=False, server_default="0")


class Visit(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "visits"

    visit_number = Column(String(30), unique=True, nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True)
    visit_type = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, server_default="registered")
    visit_date = Column(DateTime(timezone=True), nullable=False)

    # Section 4A.2 -- optimistic concurrency. GET returns this as ETag;
    # every mutating PATCH must send it back via If-Match, bumped in
    # the same transaction as the update.
    row_version = Column(Integer, nullable=False, server_default="1")

    __table_args__ = (
        CheckConstraint(
            "visit_type IN ('opd', 'ipd', 'emergency', 'teleconsult')",
            name="visit_type",
        ),
        CheckConstraint(
            "status IN ('registered', 'in_consultation', 'completed', "
            "'lwbs', 'cancelled', 'closed')",
            name="status",
        ),
        Index("ix_visits_patient_id_visit_date", "patient_id", "visit_date"),
        Index("ix_visits_facility_id", "facility_id"),
        Index("ix_visits_department_id", "department_id"),
    )


class Encounter(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "encounters"

    visit_id = Column(UUID(as_uuid=True), ForeignKey("visits.id"), nullable=False)
    provider_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    encounter_type = Column(String(50), nullable=True)
    chief_complaint = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    subjective = Column(Text, nullable=True)
    objective = Column(Text, nullable=True)
    assessment = Column(Text, nullable=True)
    plan = Column(Text, nullable=True)

    note_status = Column(String(50), nullable=False, server_default="pending")
    row_version = Column(Integer, nullable=False, server_default="1")

    __table_args__ = (
        CheckConstraint(
            "note_status IN ('pending', 'stored', 'failed')",
            name="note_status",
        ),
        Index("ix_encounters_visit_id", "visit_id"),
        Index("ix_encounters_provider_user_id", "provider_user_id"),
    )


class IcdCode(Base, UUIDPk, Timestamps):
    __tablename__ = "icd_codes"

    version = Column(String(30), nullable=False)
    code = Column(String(30), nullable=False)
    title = Column(Text, nullable=False)
    icd_uri = Column(Text, nullable=True)
    is_postcoordinable = Column(Boolean, nullable=False, server_default="false")
    is_active = Column(Boolean, nullable=False, server_default="true")

    __table_args__ = (
        UniqueConstraint("version", "code", name="uq_icd_codes_version_code"),
        Index("ix_icd_codes_icd_uri", "icd_uri"),
    )


class Diagnosis(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "diagnoses"

    encounter_id = Column(UUID(as_uuid=True), ForeignKey("encounters.id"), nullable=False)
    icd_code = Column(String(30), nullable=False)
    icd_version = Column(String(30), nullable=False)
    icd_code_id = Column(UUID(as_uuid=True), ForeignKey("icd_codes.id"), nullable=True)
    icd_uri = Column(Text, nullable=True)
    post_coordinated_code = Column(Text, nullable=True)
    diagnosis_text = Column(Text, nullable=False)
    diagnosis_type = Column(String(50), nullable=False)
    is_primary = Column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        CheckConstraint(
            "diagnosis_type IN ('provisional', 'final', 'differential')",
            name="diagnosis_type",
        ),
        Index("ix_diagnoses_icd_code_icd_version", "icd_code", "icd_version"),
    )

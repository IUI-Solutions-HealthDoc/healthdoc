from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.common.db import Base
from app.common.models import Blame, Timestamps, UUIDPk


class LabOrderItem(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "lab_order_items"

    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"),
                       nullable=False, index=True)  # order.order_type = 'lab'
    accession_number = Column(String(30), unique=True, nullable=False)
    test_code = Column(String(30), nullable=True)
    test_name = Column(Text, nullable=False)
    sample_type = Column(String(50), nullable=False)  # enum-backed: §3 blanket rule

    # ADDED for #166 -- sample collection (barcode, timestamp) was previously
    # computed in the router but never persisted anywhere. See migration
    # 00XX_lab_barcode_collected_at.py.
    barcode = Column(String(50), unique=True, nullable=True)
    collected_at = Column(DateTime(timezone=True), nullable=True)

    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"),
                            nullable=True, index=True)
    status = Column(
        String(50),
        nullable=False,
        server_default=text("'placed'")
    )
    estimated_minutes = Column(Integer, nullable=True)

    # Specimen lifecycle & rejection tracking (HD-22, migration 0077)
    specimen_status = Column(
        String(50),
        nullable=False,
        server_default=text("'pending_collection'")
    )
    rejection_reason = Column(String(50), nullable=True)
    recollected_from_id = Column(
        UUID(as_uuid=True),
        ForeignKey("lab_order_items.id", ondelete="RESTRICT"),
        nullable=True,
        index=True
    )


class LabResult(Base, UUIDPk, Timestamps):
    """
    Append-only, versioned. Corrections = new row (never UPDATE an existing result row).
    """
    __tablename__ = "lab_results"
    __table_args__ = (
        Index(
            "ix_lab_results_result_data",
            "result_data",
            postgresql_using="gin",
            postgresql_ops={"result_data": "jsonb_path_ops"},
        ),
    )

    lab_order_item_id = Column(UUID(as_uuid=True), ForeignKey("lab_order_items.id", ondelete="RESTRICT"),
                                nullable=False, index=True)
    version = Column(Integer, nullable=False)
    is_current = Column(Boolean, nullable=False)
    result_data = Column(JSONB, nullable=False)
    remarks = Column(Text, nullable=True)

    # ADDED for #218 -- required reason when a finalized result is amended.
    # NULL for original preliminary/final versions; required by the
    # amend_result endpoint for status='corrected' rows.
    amendment_reason = Column(Text, nullable=True)

    status = Column(String(50), nullable=False)

    # NOTE: not using the Blame mixin here on purpose. Blame declares BOTH
    # created_by and updated_by, but lab_results (migration 0010_lab.py) is
    # append-only/versioned -- rows are never updated in place, so there is
    # no updated_by column in the DB. Declaring it via Blame would create a
    # model attribute with no matching column. created_by alone gets the
    # real FK by hand instead, now that app.users exists on staging.
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    # UNIQUE(lab_order_item_id, version) + partial unique index WHERE is_current
    # Declared in Alembic migration (0010_lab.py), not here because
    # SQLAlchemy cannot define PostgreSQL partial unique indexes portably.


class LabAnalyte(Base, UUIDPk):
    """Structured analyte and reference interval definition for lab tests (§3 0076)."""

    __tablename__ = "lab_analytes"
    __table_args__ = (
        Index("ix_lab_analytes_test_code_version", "test_code", "version"),
    )

    test_code = Column(String(50), nullable=False)
    analyte_code = Column(String(50), nullable=False)
    analyte_name = Column(String(100), nullable=False)
    value_type = Column(String(50), nullable=False, server_default=text("'numeric'"))
    unit = Column(String(30), nullable=True)
    reference_low = Column(Numeric(10, 3), nullable=True)
    reference_high = Column(Numeric(10, 3), nullable=True)
    critical_low = Column(Numeric(10, 3), nullable=True)
    critical_high = Column(Numeric(10, 3), nullable=True)
    is_required = Column(Boolean, nullable=False, server_default=text("true"))
    version = Column(Integer, nullable=False, server_default=text("1"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LabSpecimenEvent(Base, UUIDPk):
    """Laboratory specimen collection, rejection and recollection audit trail (§3 0077)."""

    __tablename__ = "lab_specimen_events"

    lab_order_item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("lab_order_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_type = Column(String(50), nullable=False)  # collected, received, rejected, recollected
    rejection_reason = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    performed_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class CriticalAlert(Base, UUIDPk):
    """Durable panic/critical laboratory alert and acknowledgement outbox (§3 0077)."""

    __tablename__ = "critical_alerts"

    facility_id = Column(
        UUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    visit_id = Column(
        UUID(as_uuid=True),
        ForeignKey("visits.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    test_code = Column(String(50), nullable=False)
    analyte_code = Column(String(50), nullable=False)
    analyte_name = Column(String(100), nullable=False)
    value = Column(Numeric(10, 3), nullable=False)
    unit = Column(String(30), nullable=True)
    critical_low = Column(Numeric(10, 3), nullable=True)
    critical_high = Column(Numeric(10, 3), nullable=True)
    severity = Column(String(50), nullable=False, server_default=text("'critical'"))
    status = Column(String(50), nullable=False, server_default=text("'unacknowledged'"), index=True)
    acknowledged_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledgement_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.common.mixins import UUIDPk, Timestamps, Blame
from app.common.db import Base


class LabOrderItem(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "lab_order_items"

    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"),
                       nullable=False, index=True)  # order.order_type = 'lab'
    accession_number = Column(String(30), unique=True, nullable=False)
    test_code = Column(String(30), nullable=True)
    test_name = Column(Text, nullable=False)
    sample_type = Column(String(30), nullable=False)

    # ADDED for #166 — sample collection (barcode, timestamp) was previously
    # computed in the router but never persisted anywhere. See migration
    # 00XX_lab_barcode_collected_at.py.
    barcode = Column(String(50), unique=True, nullable=True)
    collected_at = Column(DateTime(timezone=True), nullable=True)

    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"),
                            nullable=True, index=True)
    status = Column(
        String(30),
        nullable=False,
        server_default=text("'placed'")
    )
    estimated_minutes = Column(Integer, nullable=True)


class LabResult(Base, UUIDPk, Timestamps):
    """
    Append-only, versioned. Corrections = new row (never UPDATE an existing result row).
    """
    __tablename__ = "lab_results"

    lab_order_item_id = Column(UUID(as_uuid=True), ForeignKey("lab_order_items.id", ondelete="RESTRICT"),
                                nullable=False, index=True)
    version = Column(Integer, nullable=False)
    is_current = Column(Boolean, nullable=False)
    result_data = Column(JSONB, nullable=False)
    remarks = Column(Text, nullable=True)

    # ADDED for #218 — required reason when a finalized result is amended.
    # NULL for original preliminary/final versions; required by the
    # amend_result endpoint for status='corrected' rows.
    amendment_reason = Column(Text, nullable=True)

    status = Column(String(30), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    # UNIQUE(lab_order_item_id, version) + partial unique index WHERE is_current
    # Declared in Alembic migration (0010_lab.py), not here because
    # SQLAlchemy cannot define PostgreSQL partial unique indexes portably.
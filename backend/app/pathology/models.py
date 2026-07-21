from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey, text
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
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"),
                            nullable=True, index=True)
    status = Column(
    String(30),
    nullable=False,
    server_default=text("'placed'")
)
    estimated_minutes = Column(Integer, nullable=True)


class LabResult(Base, UUIDPk, Timestamps, Blame):
    """
    Append-only, versioned. Corrections = new row (never UPDATE an existing result row).
    """
    __tablename__ = "lab_results"

    lab_order_item_id = Column(UUID(as_uuid=True), ForeignKey("lab_order_items.id", ondelete="RESTRICT"),
                                nullable=False, index=True)
    version = Column(Integer, nullable=False)              # 1, 2, 3 ...
    is_current = Column(Boolean, nullable=False)
    result_data = Column(JSONB, nullable=False)
    remarks = Column(Text, nullable=True)
    status = Column(String(30), nullable=False)            # ResultStatus enum
    

    # UNIQUE(lab_order_item_id, version) + partial unique index WHERE is_current
# -> declared in the Alembic migration (0010_lab.py), not here because
# SQLAlchemy cannot define PostgreSQL partial unique indexes portably.
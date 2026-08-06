from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.common.models import UUIDPk, Timestamps, Blame
from app.common.db import Base


class RadiologyOrderItem(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "radiology_order_items"

    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"),
                       nullable=False, index=True)  # order.order_type = 'radiology'
    accession_number = Column(String(30), unique=True, nullable=False)
    modality = Column(String(30), nullable=False)   # xray | ct | mri | usg | mammo
    scan_type = Column(Text, nullable=False)
    machine_id = Column(String(50), nullable=True)
    pacs_study_uid = Column(String(100), nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    scan_completed_at = Column(DateTime(timezone=True), nullable=True)  # TAT baseline
    status = Column(String(50), nullable=False, server_default="placed")


class RadiologyReport(Base, UUIDPk, Timestamps):
    """
    Append-only, versioned - same pattern as lab_results, but narrative
    findings/impression text instead of structured result_data.
    """
    __tablename__ = "radiology_reports"

    radiology_order_item_id = Column(UUID(as_uuid=True),
                                      ForeignKey("radiology_order_items.id", ondelete="RESTRICT"),
                                      nullable=False, index=True)
    version = Column(Integer, nullable=False)
    is_current = Column(Boolean, nullable=False)
    findings = Column(Text, nullable=False)
    impression = Column(Text, nullable=False)
    status = Column(String(50), nullable=False)     # ResultStatus enum

    # NOTE: not using Blame here -- same reason as LabResult in pathology:
    # radiology_reports (migration 0011_radiology.py) only has created_by,
    # no updated_by column, since these rows are append-only/versioned and
    # never updated in place.
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

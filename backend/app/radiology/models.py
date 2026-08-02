from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.common.mixins import UUIDPk, Timestamps
from app.common.db import Base


class RadiologyOrderItem(Base, UUIDPk, Timestamps):
    __tablename__ = "radiology_order_items"

    # NOTE: not using the Blame mixin here — it hardcodes ForeignKey("users.id"),
    # and app.users has no models.py/table yet (confirmed 2026-07-30). Using
    # plain UUID columns instead. Switch back to the Blame mixin once
    # app.users exists.
    created_by = Column(UUID(as_uuid=True), nullable=False)
    updated_by = Column(UUID(as_uuid=True), nullable=True)

    # NOTE: FK to orders.id intentionally omitted — app.orders has no
    # models.py yet (confirmed 2026-07-30).
    order_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # order.order_type = 'radiology'
    accession_number = Column(String(30), unique=True, nullable=False)
    modality = Column(String(30), nullable=False)   # xray | ct | mri | usg | mammo
    scan_type = Column(Text, nullable=False)
    machine_id = Column(String(50), nullable=True)
    pacs_study_uid = Column(String(100), nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    scan_completed_at = Column(DateTime(timezone=True), nullable=True)  # TAT baseline
    status = Column(String(30), nullable=False, server_default="placed")


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
    status = Column(String(30), nullable=False)     # ResultStatus enum

    # NOTE: FK to users.id intentionally omitted — app.users has no
    # models.py yet (confirmed 2026-07-30).
    created_by = Column(UUID(as_uuid=True), nullable=False)
"""What HealthDoc sent HFR for each facility it registered (M4 HFR-064 to 117).

HFR has no call that returns a facility's saved details, yet editing one
(HFR-064 to 114) re-sends basic and detailed information under the same
tracking id, then resubmits. Without this row the administrator would retype
every field to change one. Each step's form is kept as it was accepted, minus
the board, building and address-proof images: those go to HFR only, and are
attached again for an edit.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.common.db import Base
from app.common.models import Blame, Timestamps, UUIDPk


class AbdmHfrRegistration(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "abdm_hfr_registrations"

    facility_id = Column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    #: HFR's own key for the facility's details; every edit continues it.
    tracking_id = Column(String(20), nullable=False)
    #: Set by submit-facility (HFR-116); a 12-character id starting IN.
    hfr_facility_id = Column(String(12), nullable=True)
    #: The status HFR returned for the last step, as it sent it (Draft,
    #: Submitted, Created...). Read, never assumed.
    status = Column(String(50), nullable=True)
    #: Each step's form as HFR accepted it, without image content.
    basic = Column(JSONB, nullable=True)
    additional = Column(JSONB, nullable=True)
    detailed = Column(JSONB, nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("facility_id", "tracking_id", name="uq_abdm_hfr_registrations_tracking"),
        Index("ix_abdm_hfr_registrations_created_by", "created_by"),
        Index("ix_abdm_hfr_registrations_updated_by", "updated_by"),
    )

    __audit_resource_type__ = "abdm_hfr_registrations"
    __audit_facility_id_field__ = "facility_id"

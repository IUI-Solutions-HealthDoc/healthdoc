"""ORM model for migration 0028's maker-checker account requests."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk


class UserAccountRequest(Base, UUIDPk, Timestamps):
    __tablename__ = "user_account_requests"
    __table_args__ = (
        CheckConstraint("decided_by IS NULL OR decided_by != requested_by",
                        name="ck_user_account_requests_requester_ne_approver"),
        CheckConstraint("status IN ('pending','approved','rejected')",
                        name="ck_user_account_requests_status"),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    requested_for_full_name: Mapped[str] = mapped_column(Text, nullable=False)
    requested_username: Mapped[str] = mapped_column(String(100), nullable=False)
    requested_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(100))
    employee_id: Mapped[str | None] = mapped_column(String(30))
    registration_number: Mapped[str | None] = mapped_column(String(50))
    qualification: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    mobile: Mapped[str | None] = mapped_column(String(20))
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )

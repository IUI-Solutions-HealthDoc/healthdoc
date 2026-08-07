"""user_account_requests model — migration 0028. Maker-checker for account requests."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import UUIDPk, Timestamps, Blame


class UserAccountRequest(Base, UUIDPk, Timestamps):
    __tablename__ = "user_account_requests"
    __table_args__ = (
        CheckConstraint(
            "approver_id IS NULL OR approver_id != requester_id",
            name="ck_user_account_requests_requester_ne_approver",
        ),
        CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_user_account_requests_status",
        ),
    )

    username: Mapped[str] = mapped_column(String(100), nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    mobile: Mapped[str | None] = mapped_column(String(20))
    designation: Mapped[str | None] = mapped_column(String(100))
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    requested_roles: Mapped[str | None] = mapped_column(String(500))
    justification: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    approver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True, index=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

"""Allergy register — schema v3.14 §3 0032.

Matching is on `ingredient_code`, never on `inventory_item_id`: a penicillin allergy has
to fire on amoxicillin, which is a different `inventory_items` row.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.enums import AllergenType, AllergySeverity, AllergyStatus
from app.common.models import Blame, Timestamps, UUIDPk


class Allergy(Base, UUIDPk, Timestamps, Blame):
    __tablename__ = "allergies"
    __table_args__ = (
        CheckConstraint(AllergenType.sql_check("allergen_type"),
                        name="ck_allergies_allergen_type"),
        CheckConstraint(AllergySeverity.sql_check("severity"), name="ck_allergies_severity"),
        CheckConstraint(AllergyStatus.sql_check("status"), name="ck_allergies_status"),
        CheckConstraint("(verified_by IS NULL) = (verified_at IS NULL)",
                        name="ck_allergies_verification_complete"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    allergen_type: Mapped[str] = mapped_column(String(50), nullable=False)

    #: Always populated, even when coded — "penicillin injection" from an attendant is
    #: the whole record in a rural OPD, and it must never be lost to a failed lookup.
    substance_text: Mapped[str] = mapped_column(Text, nullable=False)

    #: The matchable key. NULL means display-only: shown in the banner, can never block.
    ingredient_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=True)

    reaction: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="active")
    onset_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    @property
    def is_blocking(self) -> bool:
        """Only a coded, active allergy can block a prescription.

        An uncoded allergy is real and shown, but the system cannot prove a match — so
        it must not claim to. Callers surface this to the UI so the clinician knows the
        difference between "checked and clear" and "could not check".
        """
        return self.status == AllergyStatus.ACTIVE.value and self.ingredient_code is not None

    @property
    def is_absolute(self) -> bool:
        """Anaphylaxis is never overridable, by any role."""
        return self.severity == AllergySeverity.ANAPHYLAXIS.value

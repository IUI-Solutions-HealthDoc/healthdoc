"""Diet orders and meals served to admitted patients (migration 0104).

A diet order says what an admitted patient may eat: a diet type and the
clinician's instructions. One is active per admission at a time; changing the
diet stops the old order and starts a new one, so the kitchen's history of
"what was this patient on, when" is a fact, not an overwrite.

A meal service is one meal on one day for one admission: served, refused by
the patient, or not served (with why). The kitchen board is built from these.

Both hang off the admission, not the patient: a merge repoints admissions, and
the diet belongs to the stay.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk

DIET_TYPES = (
    "normal", "soft", "liquid", "clear_liquid", "diabetic", "renal", "low_salt", "low_fat",
    "high_protein", "semi_solid", "tube_feed", "npo", "other",
)
DIET_ORDER_STATUSES = ("active", "stopped")
MEALS = ("early_morning", "breakfast", "mid_morning", "lunch", "evening_snack", "dinner", "bedtime")
MEAL_STATUSES = ("served", "refused", "not_served")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class DietOrder(Base, UUIDPk, Timestamps):
    __tablename__ = "diet_orders"
    __audit_resource_type__ = "diet_orders"
    __audit_facility_id_field__ = "facility_id"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=False
    )
    diet_type: Mapped[str] = mapped_column(String(50), nullable=False)
    #: What the kitchen must know: "no sugar", "1.5 L fluid restriction", "Jain, no onion/garlic".
    instructions: Mapped[str | None] = mapped_column(Text)
    #: Food allergies as the clinician states them. Free text on purpose: the
    #: allergy register is coded for drugs; a kitchen reads "peanuts".
    food_allergies: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", server_default="active")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ordered_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    stop_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(f"diet_type IN ({_in(DIET_TYPES)})", name="ck_diet_orders_diet_type"),
        CheckConstraint(f"status IN ({_in(DIET_ORDER_STATUSES)})", name="ck_diet_orders_status"),
        # "Other" says nothing to the kitchen by itself.
        CheckConstraint(
            "diet_type <> 'other' OR (instructions IS NOT NULL AND trim(instructions) <> '')",
            name="ck_diet_orders_other_needs_instructions",
        ),
        CheckConstraint("status <> 'stopped' OR stopped_at IS NOT NULL", name="ck_diet_orders_stopped_at"),
        # One diet in force per stay; a change stops the old order first.
        Index(
            "uq_diet_orders_active_admission", "admission_id", unique=True,
            sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'"),
        ),
        Index("ix_diet_orders_facility_status", "facility_id", "status"),
        Index("ix_diet_orders_ordered_by", "ordered_by"),
        Index("ix_diet_orders_stopped_by", "stopped_by"),
    )


class MealService(Base, UUIDPk, Timestamps):
    """One meal, one day, one admission. Recorded once; a mistake is corrected, not re-recorded."""

    __tablename__ = "meal_services"
    __audit_resource_type__ = "meal_services"
    __audit_facility_id_field__ = "facility_id"
    __table_args__ = (
        CheckConstraint(f"meal IN ({_in(MEALS)})", name="ck_meal_services_meal"),
        CheckConstraint(f"status IN ({_in(MEAL_STATUSES)})", name="ck_meal_services_status"),
        CheckConstraint(
            "status <> 'not_served' OR (notes IS NOT NULL AND trim(notes) <> '')",
            name="ck_meal_services_not_served_reason",
        ),
        Index("uq_meal_services_admission_day_meal", "admission_id", "service_date", "meal", unique=True),
        Index("ix_meal_services_facility_day", "facility_id", "service_date"),
        Index("ix_meal_services_diet_order_id", "diet_order_id"),
        Index("ix_meal_services_recorded_by", "recorded_by"),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=False
    )
    #: The order in force when the meal went out: what the tray should have been.
    diet_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("diet_orders.id", ondelete="RESTRICT")
    )
    #: The ward's calendar day (Asia/Kolkata), not UTC's.
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    meal: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

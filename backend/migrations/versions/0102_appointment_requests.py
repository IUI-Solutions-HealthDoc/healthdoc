"""Patient-portal appointment requests.

Revision ID: 0102
Revises: 0101
Create Date: 2026-10-10

A patient (or the guardian holding the portal binding) asks for a department,
a date, morning or afternoon, in person or by teleconsultation. Reception
confirms it with a time, which creates a normal appointment through the desk's
own checks, or declines it with a reason the patient sees. HealthDoc records
shift names, not clinic hours, so it does not invent bookable slots.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0102"
down_revision = "0101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appointment_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("department_id", UUID(as_uuid=True), sa.ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("preferred_date", sa.Date(), nullable=False),
        sa.Column("session", sa.String(50), nullable=False),
        sa.Column("is_teleconsult", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="requested"),
        sa.Column("appointment_id", UUID(as_uuid=True), sa.ForeignKey("appointments.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("decided_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('requested', 'confirmed', 'declined', 'withdrawn')", name="appointment_request_status"
        ),
        sa.CheckConstraint("session IN ('morning', 'afternoon')", name="appointment_request_session"),
        sa.CheckConstraint(
            "(status = 'confirmed') = (appointment_id IS NOT NULL)",
            name="appointment_request_confirmed_has_appointment",
        ),
        sa.CheckConstraint(
            "status <> 'declined' OR (decline_reason IS NOT NULL AND trim(decline_reason) <> '')",
            name="appointment_request_decline_reason",
        ),
    )
    for name, columns in (
        ("ix_appointment_requests_facility_status", ["facility_id", "status", "preferred_date"]),
        ("ix_appointment_requests_patient_id", ["patient_id"]),
        ("ix_appointment_requests_requested_by", ["requested_by"]),
        ("ix_appointment_requests_department_id", ["department_id"]),
        ("ix_appointment_requests_appointment_id", ["appointment_id"]),
        ("ix_appointment_requests_decided_by", ["decided_by"]),
    ):
        op.create_index(name, "appointment_requests", columns)


def downgrade() -> None:
    op.drop_table("appointment_requests")

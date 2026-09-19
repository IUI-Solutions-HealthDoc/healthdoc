"""Critical alerts outbox, LIS specimen tracking, radiology attachments, and pharmacy returns (HD-21 to HD-24).

Revision ID: 0077
Revises: 0076
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------- 1. HD-21: CRITICAL ALERTS & TRANSACTIONAL OUTBOX ----------------
    op.create_table(
        "critical_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("visits.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("test_code", sa.String(length=50), nullable=False),
        sa.Column("analyte_code", sa.String(length=50), nullable=False),
        sa.Column("analyte_name", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Numeric(10, 3), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column("critical_low", sa.Numeric(10, 3), nullable=True),
        sa.Column("critical_high", sa.Numeric(10, 3), nullable=True),
        sa.Column("severity", sa.String(length=50), nullable=False, server_default=sa.text("'critical'")),
        sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'unacknowledged'")),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledgement_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("severity IN ('critical', 'panic', 'urgent')", name="ck_critical_alerts_severity"),
        sa.CheckConstraint("status IN ('unacknowledged', 'acknowledged', 'escalated')", name="ck_critical_alerts_status"),
    )
    op.create_index("ix_critical_alerts_facility_id", "critical_alerts", ["facility_id"])
    op.create_index("ix_critical_alerts_patient_id", "critical_alerts", ["patient_id"])
    op.create_index("ix_critical_alerts_visit_id", "critical_alerts", ["visit_id"])
    op.create_index("ix_critical_alerts_order_id", "critical_alerts", ["order_id"])
    op.create_index("ix_critical_alerts_acknowledged_by", "critical_alerts", ["acknowledged_by"])
    op.create_index("ix_critical_alerts_created_at", "critical_alerts", ["created_at"])
    op.create_index("ix_critical_alerts_status", "critical_alerts", ["status"])

    # ---------------- 2. HD-22: LIS SPECIMEN TRACKING & REJECTION ----------------
    op.add_column(
        "lab_order_items",
        sa.Column("specimen_status", sa.String(length=50), nullable=False, server_default=sa.text("'pending_collection'")),
    )
    op.add_column(
        "lab_order_items",
        sa.Column("rejection_reason", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "lab_order_items",
        sa.Column(
            "recollected_from_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lab_order_items.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_lab_order_items_recollected_from_id", "lab_order_items", ["recollected_from_id"])
    op.create_check_constraint(
        "ck_lab_order_items_specimen_status",
        "lab_order_items",
        "specimen_status IN ('pending_collection', 'collected', 'received', 'rejected', 'recollected')",
    )

    op.create_table(
        "lab_specimen_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lab_order_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lab_order_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("rejection_reason", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("performed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "event_type IN ('collected', 'received', 'rejected', 'recollected')",
            name="ck_lab_specimen_events_type",
        ),
        sa.CheckConstraint(
            "rejection_reason IS NULL OR rejection_reason IN ('hemolyzed', 'clotted', 'insufficient_volume', 'mislabeled', 'compromised')",
            name="ck_lab_specimen_events_rejection_reason",
        ),
    )
    op.create_index("ix_lab_specimen_events_order_item_id", "lab_specimen_events", ["lab_order_item_id"])
    op.create_index("ix_lab_specimen_events_performed_by", "lab_specimen_events", ["performed_by"])

    # ---------------- 3. HD-23: RADIOLOGY / IMAGING ATTACHMENTS ----------------
    op.create_table(
        "radiology_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column(
            "radiology_order_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("radiology_order_items.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("file_key", sa.String(length=255), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_radiology_attachments_facility_id", "radiology_attachments", ["facility_id"])
    op.create_index("ix_radiology_attachments_order_id", "radiology_attachments", ["order_id"])
    op.create_index("ix_radiology_attachments_patient_id", "radiology_attachments", ["patient_id"])
    op.create_index("ix_radiology_attachments_item_id", "radiology_attachments", ["radiology_order_item_id"])
    op.create_index("ix_radiology_attachments_uploaded_by", "radiology_attachments", ["uploaded_by"])

    # ---------------- 4. HD-24: PHARMACY RETURNS & QUARANTINE LEDGER ----------------
    op.create_table(
        "pharmacy_returns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("dispense_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pharmacy_dispenses.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_batches.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("return_reason", sa.Text(), nullable=False),
        sa.Column("disposition", sa.String(length=50), nullable=False, server_default=sa.text("'quarantine'")),
        sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'completed'")),
        sa.Column("returned_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quantity > 0", name="ck_pharmacy_returns_positive_qty"),
        sa.CheckConstraint("disposition IN ('quarantine', 'resalable')", name="ck_pharmacy_returns_disposition"),
        sa.CheckConstraint("status IN ('pending', 'completed', 'cancelled')", name="ck_pharmacy_returns_status"),
    )
    op.create_index("ix_pharmacy_returns_facility_id", "pharmacy_returns", ["facility_id"])
    op.create_index("ix_pharmacy_returns_patient_id", "pharmacy_returns", ["patient_id"])
    op.create_index("ix_pharmacy_returns_dispense_id", "pharmacy_returns", ["dispense_id"])
    op.create_index("ix_pharmacy_returns_item_id", "pharmacy_returns", ["item_id"])
    op.create_index("ix_pharmacy_returns_batch_id", "pharmacy_returns", ["batch_id"])
    op.create_index("ix_pharmacy_returns_returned_by", "pharmacy_returns", ["returned_by"])


def downgrade() -> None:
    # 4. Drop pharmacy returns
    op.drop_table("pharmacy_returns")

    # 3. Drop radiology attachments
    op.drop_table("radiology_attachments")

    # 2. Drop lab specimen events & columns
    op.drop_table("lab_specimen_events")
    op.drop_constraint("ck_lab_order_items_specimen_status", "lab_order_items", type_="check")
    op.drop_index("ix_lab_order_items_recollected_from_id", table_name="lab_order_items")
    op.drop_column("lab_order_items", "recollected_from_id")
    op.drop_column("lab_order_items", "rejection_reason")
    op.drop_column("lab_order_items", "specimen_status")

    # 1. Drop critical alerts
    op.drop_table("critical_alerts")

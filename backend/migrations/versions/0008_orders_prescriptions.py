"""0008_orders_prescriptions

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-23

Builds: orders, prescriptions, prescription_items, procedure_records,
        order_external_results (schema.md §3, migration 0008)
Depends on: 0007 visits/encounters.

Two deferred FKs, both following the prescription_items.medicine_item_id
precedent — the column exists now, the constraint arrives with the migration
that creates its target:
  procedure_records.ot_schedule_id      -> ot_schedules (0017)
  order_external_results.result_file_id -> files        (0019)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------- orders
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                   server_default=sa.text("uuid_generate_v4()")),
        sa.Column("order_number", sa.String(30), nullable=False),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_type", sa.String(50), nullable=False),
        sa.Column("priority", sa.String(50), nullable=False, server_default="routine"),
        sa.Column("status", sa.String(50), nullable=False, server_default="placed"),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.UniqueConstraint("order_number", name="uq_orders_order_number"),
        sa.CheckConstraint(
            "order_type IN ('lab','radiology','pharmacy','procedure','blood')",
            name="ck_orders_order_type",
        ),
        sa.CheckConstraint("priority IN ('routine','urgent','stat')", name="ck_orders_priority"),
        sa.CheckConstraint(
            "status IN ('placed','in_progress','completed','cancelled')", name="ck_orders_status"
        ),
    )
    op.create_index("ix_orders_order_type_status", "orders", ["order_type", "status"])
    op.create_index("ix_orders_patient_id", "orders", ["patient_id"])
    op.create_index("ix_orders_encounter_id", "orders", ["encounter_id"])

    # ---------------------------------------------------- prescriptions
    op.create_table(
        "prescriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                   server_default=sa.text("uuid_generate_v4()")),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
    )
    op.create_index("ix_prescriptions_encounter_id", "prescriptions", ["encounter_id"])
    op.create_index("ix_prescriptions_patient_id", "prescriptions", ["patient_id"])

    # ----------------------------------------------- prescription_items
    op.create_table(
        "prescription_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                   server_default=sa.text("uuid_generate_v4()")),
        sa.Column("prescription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("medicine_item_id", postgresql.UUID(as_uuid=True), nullable=True),  # FK added in 0012
        sa.Column("medicine_name", sa.Text, nullable=False),
        sa.Column("dosage", sa.String(50), nullable=True),
        sa.Column("frequency", sa.String(50), nullable=True),
        sa.Column("duration_days", sa.Integer, nullable=True),
        sa.Column("route", sa.String(30), nullable=True),
        sa.Column("instructions", sa.Text, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="prescribed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["prescription_id"], ["prescriptions.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('prescribed','dispensed','partially_dispensed','on_hold','cancelled')",
            name="ck_prescription_items_status",
        ),
    )
    op.create_index("ix_prescription_items_prescription_id", "prescription_items", ["prescription_id"])

    # ------------------------------------------------ procedure_records
    # Owned by orders/B3, NOT the OT module — a suture, dressing or
    # catheterisation must be recordable at a facility with no theatre, and
    # billing reads this table for the `procedure` charge category. So
    # ot_schedule_id is nullable and its FK waits for 0017, the same way
    # prescription_items.medicine_item_id waits for 0012.
    op.create_table(
        "procedure_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                   server_default=sa.text("uuid_generate_v4()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("procedure_name", sa.Text, nullable=False),
        sa.Column("procedure_code", sa.String(30), nullable=True),
        sa.Column("code_system", sa.String(30), nullable=True),
        sa.Column("setting", sa.String(50), nullable=False),
        sa.Column("ot_schedule_id", postgresql.UUID(as_uuid=True), nullable=True),  # FK added in 0017
        sa.Column("performed_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assisted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.Text, nullable=True),
        sa.Column("complications", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["performed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["assisted_by"], ["users.id"]),
        sa.CheckConstraint(
            "setting IN ('opd_minor','bedside','emergency','ot')",
            name="ck_procedure_records_setting",
        ),
        sa.CheckConstraint(
            "ot_schedule_id IS NULL OR setting = 'ot'",
            name="ck_procedure_records_ot_schedule_only_when_ot",
        ),
    )
    op.create_index("ix_procedure_records_encounter_id", "procedure_records", ["encounter_id"])
    op.create_index("ix_procedure_records_patient_id", "procedure_records", ["patient_id"])

    # ------------------------------------------- order_external_results
    # Owned by orders/B3, deliberately not the lab module, so off-site
    # fulfilment still works with lab and radiology switched off.
    # Append-only by convention (§3): a corrected outside report is a NEW
    # row, never an UPDATE — same versioning philosophy as lab_results.
    # result_file_id's FK to files arrives with 0019.
    op.create_table(
        "order_external_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                   server_default=sa.text("uuid_generate_v4()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_name", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("result_file_id", postgresql.UUID(as_uuid=True), nullable=True),  # FK added in 0019
        sa.Column("observed_on", sa.Date, nullable=True),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
    )
    op.create_index("ix_order_external_results_order_id", "order_external_results", ["order_id"])


def downgrade() -> None:
    op.drop_table("order_external_results")
    op.drop_table("procedure_records")
    op.drop_table("prescription_items")
    op.drop_table("prescriptions")
    op.drop_table("orders")
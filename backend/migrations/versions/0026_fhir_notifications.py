"""0026_fhir_notifications

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-11

Builds: fhir_bundle_transactions, discharge_notifications
        (schema.md §3, migration 0026)

The last of the three unwritten migrations. No issue existed for it either —
§2 assigns it jointly to B7 and B4, which is part of why neither picked it
up. Transcribed from §3.

This one matters most for unblocking: Ajay's 0027 chains off it, and 0028
through 0031 chain off that. Six PRs, written and green for four days,
waiting on two tables.

fhir_bundle_transactions is the Postgres audit of every ABDM transmission —
the payloads live in Mongo, this row is the auditable fact. That split is
deliberate: a Mongo outage must not lose the record that a transmission
happened, and ABDM compliance questions are answered from Postgres.

discharge_notifications is durable rather than fire-and-forget. UNIQUE
(discharge_id, target_module) means a discharge notifies each module exactly
once — a retry updates the existing row instead of queuing a second one.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.common.enums import NotificationStatus

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------ fhir_bundle_transactions
    op.create_table(
        "fhir_bundle_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bundle_id", sa.String(100), nullable=False),
        sa.Column("abdm_request_id", sa.String(100), nullable=True),
        sa.Column("direction", sa.String(30), nullable=False),
        sa.Column("care_context_linked", sa.Boolean(), nullable=True),
        sa.Column("gateway_response_status", sa.String(50), nullable=True),
        sa.Column("signed_by_hpr_id", sa.String(50), nullable=True),
        # Nullable: a gateway handshake or a failed push may have no patient
        # resolved yet, and losing the record of the attempt is worse than
        # storing it without one.
        sa.Column("patient_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("consent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("consent_records.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("transmitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("direction IN ('hip_push','hiu_pull')",
                           name="ck_fhir_bundle_transactions_direction"),
    )
    # (patient_id, transmitted_at) per §3 — the query this serves is "what
    # was transmitted about this patient, and when", which is exactly the
    # question a DPDP access request asks.
    op.create_index("ix_fhir_bundle_transactions_patient_id",
                    "fhir_bundle_transactions", ["patient_id", "transmitted_at"])
    op.create_index("ix_fhir_bundle_transactions_facility_id",
                    "fhir_bundle_transactions", ["facility_id"])

    # ------------------------------------------- discharge_notifications
    op.create_table(
        "discharge_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("discharge_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("discharges.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_module", sa.String(30), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="queued"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        # One notification per module per discharge. A retry updates this
        # row; it does not queue a second one. Without this, a flaky link
        # means pharmacy gets told three times to prepare discharge meds.
        sa.UniqueConstraint("discharge_id", "target_module",
                            name="uq_discharge_notifications_discharge_id_target_module"),
        sa.CheckConstraint(
            "target_module IN ('pharmacy','billing','nursing','lab',"
            "'radiology','patient')",
            name="ck_discharge_notifications_target_module",
        ),
        # NotificationStatus.sql_check() rather than a literal list: §3 names
        # the enum, and a hand-written list is how the doc and the code drift
        # apart. Note 'acknowledged' is NOT a status — delivery and receipt
        # are different facts, and receipt lives in acknowledged_at/_by.
        sa.CheckConstraint(
            NotificationStatus.sql_check("status"),
            name="ck_discharge_notifications_status",
        ),
    )
    op.create_index("ix_discharge_notifications_discharge_id",
                    "discharge_notifications", ["discharge_id"])


def downgrade() -> None:
    op.drop_index("ix_discharge_notifications_discharge_id",
                  table_name="discharge_notifications")
    op.drop_table("discharge_notifications")
    op.drop_index("ix_fhir_bundle_transactions_facility_id",
                  table_name="fhir_bundle_transactions")
    op.drop_index("ix_fhir_bundle_transactions_patient_id",
                  table_name="fhir_bundle_transactions")
    op.drop_table("fhir_bundle_transactions")

"""Inpatient dispositions and admission checklist tables (HD-13 to HD-16).

Revision ID: 0075
Revises: 0074
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------- 1. CLINICAL DISPOSITIONS (HD-13) ----------------
    op.create_table(
        "clinical_dispositions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "facility_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("facilities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "visit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("visits.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "encounter_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("encounters.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("disposition_type", sa.String(50), nullable=False),
        sa.Column("priority", sa.String(50), nullable=False, server_default="routine"),
        sa.Column(
            "recommended_ward_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wards.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "recommended_department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "disposition_type IN ('admit', 'discharge', 'transfer', 'follow_up')",
            name="ck_clinical_dispositions_disposition_type",
        ),
        sa.CheckConstraint(
            "priority IN ('routine', 'urgent', 'emergency')",
            name="ck_clinical_dispositions_priority",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'admitted', 'discharged', 'transferred', 'cancelled')",
            name="ck_clinical_dispositions_status",
        ),
    )

    # Supporting indexes for clinical_dispositions foreign keys and query patterns
    op.create_index(
        "ix_clinical_dispositions_facility_id",
        "clinical_dispositions",
        ["facility_id"],
    )
    op.create_index(
        "ix_clinical_dispositions_patient_id",
        "clinical_dispositions",
        ["patient_id"],
    )
    op.create_index(
        "ix_clinical_dispositions_visit_id",
        "clinical_dispositions",
        ["visit_id"],
    )
    op.create_index(
        "ix_clinical_dispositions_encounter_id",
        "clinical_dispositions",
        ["encounter_id"],
    )
    op.create_index(
        "ix_clinical_dispositions_recommended_ward_id",
        "clinical_dispositions",
        ["recommended_ward_id"],
    )
    op.create_index(
        "ix_clinical_dispositions_recommended_department_id",
        "clinical_dispositions",
        ["recommended_department_id"],
    )
    op.create_index(
        "ix_clinical_dispositions_created_by",
        "clinical_dispositions",
        ["created_by"],
    )
    op.create_index(
        "ix_clinical_dispositions_updated_by",
        "clinical_dispositions",
        ["updated_by"],
    )
    op.create_index(
        "ix_clinical_dispositions_status",
        "clinical_dispositions",
        ["facility_id", "status"],
    )

    # ---------------- 2. ADMISSION CHECKLIST TASKS (HD-16) ----------------
    op.create_table(
        "admission_checklist_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "admission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "facility_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("facilities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("task_code", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("category", sa.String(50), nullable=False, server_default="general"),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "completed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("skipped_reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "admission_id", "task_code", name="uq_admission_checklist_tasks_admission_task"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'skipped')",
            name="ck_admission_checklist_tasks_status",
        ),
        sa.CheckConstraint(
            "status <> 'skipped' OR (skipped_reason IS NOT NULL AND length(trim(skipped_reason)) > 0)",
            name="ck_admission_checklist_tasks_skip_reason_required",
        ),
    )

    # Supporting indexes for admission_checklist_tasks foreign keys
    op.create_index(
        "ix_admission_checklist_tasks_admission_id",
        "admission_checklist_tasks",
        ["admission_id"],
    )
    op.create_index(
        "ix_admission_checklist_tasks_facility_id",
        "admission_checklist_tasks",
        ["facility_id"],
    )
    op.create_index(
        "ix_admission_checklist_tasks_completed_by",
        "admission_checklist_tasks",
        ["completed_by"],
    )


def downgrade() -> None:
    op.drop_table("admission_checklist_tasks")
    op.drop_table("clinical_dispositions")

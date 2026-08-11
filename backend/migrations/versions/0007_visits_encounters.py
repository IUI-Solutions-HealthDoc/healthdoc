"""0007_visits_encounters

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-23

Builds: visits, encounters, icd_codes, diagnoses  (schema.md §3, migration 0007)
Depends on: 0006 patients, 0005 departments, 0002 facilities/users.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------- visits
    op.create_table(
        "visits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("visit_number", sa.String(30), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("visit_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="registered"),
        sa.Column("visit_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["facility_id"], ["facilities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.UniqueConstraint("visit_number", name="uq_visits_visit_number"),
        sa.CheckConstraint(
            "visit_type IN ('opd','ipd','emergency','teleconsult')",
            name="ck_visits_visit_type",
        ),
        sa.CheckConstraint(
            "status IN ('registered','payment_pending','waiting','in_service',"
            "'waiting_for_investigation','report_ready','doctor_review_pending',"
            "'pharmacy_pending','completed','cancelled','lwbs')",
            name="ck_visits_status",
        ),
    )
    op.create_index("ix_visits_patient_id_visit_date", "visits", ["patient_id", "visit_date"])
    op.create_index("ix_visits_facility_id", "visits", ["facility_id"])
    op.create_index("ix_visits_department_id", "visits", ["department_id"])

    # ------------------------------------------------------- encounters
    op.create_table(
        "encounters",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("encounter_type", sa.String(50), nullable=True),
        sa.Column("chief_complaint", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.CheckConstraint(
            "encounter_type IN ('consultation','follow_up','emergency','ward_round')",
            name="ck_encounters_encounter_type",
        ),
    )
    op.create_index("ix_encounters_visit_id", "encounters", ["visit_id"])
    op.create_index("ix_encounters_provider_user_id", "encounters", ["provider_user_id"])

    # --------------------------------------------------------- icd_codes
    op.create_table(
        "icd_codes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("icd_uri", sa.Text, nullable=True),
        sa.Column("is_postcoordinable", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("version", "code", name="uq_icd_codes_version_code"),
        sa.CheckConstraint("version IN ('icd10','icd11')", name="ck_icd_codes_version"),
    )
    op.create_index("ix_icd_codes_icd_uri", "icd_codes", ["icd_uri"])

    # --------------------------------------------------------- diagnoses
    op.create_table(
        "diagnoses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("icd_code", sa.String(30), nullable=False),
        sa.Column("icd_version", sa.String(50), nullable=False),
        sa.Column("icd_code_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("icd_uri", sa.Text, nullable=True),
        sa.Column("post_coordinated_code", sa.Text, nullable=True),
        sa.Column("diagnosis_text", sa.Text, nullable=False),
        sa.Column("diagnosis_type", sa.String(50), nullable=False),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["icd_code_id"], ["icd_codes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.CheckConstraint("icd_version IN ('icd10','icd11')", name="ck_diagnoses_icd_version"),
        sa.CheckConstraint(
            "diagnosis_type IN ('provisional','final','differential')",
            name="ck_diagnoses_diagnosis_type",
        ),
    )
    op.create_index("ix_diagnoses_icd_code_icd_version", "diagnoses", ["icd_code", "icd_version"])
    op.create_index("ix_diagnoses_encounter_id", "diagnoses", ["encounter_id"])
    op.create_index("ix_diagnoses_icd_code_id", "diagnoses", ["icd_code_id"])


def downgrade() -> None:
    op.drop_table("diagnoses")
    op.drop_table("icd_codes")
    op.drop_table("encounters")
    op.drop_table("visits")
"""0015_admissions_discharge

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-09

Builds: wards, beds, admissions, discharges (schema.md §3, migration 0015)
Depends on: 0005 departments, 0006 patients, 0007 visits, 0002 facilities/users.

WHY THIS EXISTS SEPARATELY FROM THE MODELS
------------------------------------------
app/admissions/models.py landed with #289 and declares all four of these
tables, but no migration created them — the ORM described a schema the
database did not have. 0015 is also the keystone of the remaining chain:
0016 (blood bank) and 0017 (OT stubs) both wait on it, and 0019/0020 sit
parked behind 0017. Transcribed from §3 and from those merged models,
which already agree with each other.

Constraint names are spelled out in full here. op.create_table does NOT
apply app/common/db.py's NAMING_CONVENTION — alembic uses whatever name it
is given verbatim — so these are the exact names the ORM must also produce
once its already-prefixed name= arguments are corrected to bare ones.

beds.status is varchar(50), not the varchar(30) in §3's beds line. Every
enum-backed column is 50 under the §3 blanket rule (v3.4.1), which
post-dates that line, and app/admissions/models.py already uses 50. The §3
line is stale; the rule wins.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------ wards
    op.create_table(
        "wards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.Text(), nullable=False),
        # Nullable on purpose: a ward need not belong to a department
        # (general wards, observation areas). §3 marks it NULL.
        sa.Column("department_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("departments.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_wards_department_id", "wards", ["department_id"])
    op.create_index("ix_wards_facility_id", "wards", ["facility_id"])

    # ------------------------------------------------------------- beds
    op.create_table(
        "beds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("ward_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("wards.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("bed_number", sa.String(20), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="vacant"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("ward_id", "bed_number", name="uq_beds_ward_id_bed_number"),
        sa.CheckConstraint(
            "status IN ('vacant','occupied','reserved','maintenance')",
            name="ck_beds_status",
        ),
    )
    # No separate ward_id index: uq_beds_ward_id_bed_number leads with
    # ward_id, so it already serves ward-scoped lookups.

    # ------------------------------------------------------- admissions
    op.create_table(
        "admissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("visits.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        # Real FKs, never varchar ward/bed names — §3 calls this out
        # explicitly. A bed name typed as text cannot be checked for
        # double-occupancy or reconciled against the ward it belongs to.
        sa.Column("ward_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("wards.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("bed_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("beds.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="admitted"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('admitted','transferred','discharged','dama','deceased','absconded')",
            name="ck_admissions_status",
        ),
    )
    op.create_index("ix_admissions_visit_id", "admissions", ["visit_id"])
    op.create_index("ix_admissions_patient_id", "admissions", ["patient_id"])
    op.create_index("ix_admissions_ward_id", "admissions", ["ward_id"])
    op.create_index("ix_admissions_bed_id", "admissions", ["bed_id"])

    # ------------------------------------------------------- discharges
    op.create_table(
        "discharges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        # UNIQUE, not just FK: one admission discharges exactly once. A
        # second discharge row for the same admission is a data error, not
        # a correction — corrections amend the existing row.
        sa.Column("admission_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("admissions.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("discharged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("discharge_type", sa.String(50), nullable=False),
        # Long-form summary goes to Mongo clinical_notes eventually; plain
        # text here for MVP, matching app/admissions/models.py.
        sa.Column("discharge_summary", sa.Text(), nullable=True),
        sa.Column("follow_up_date", sa.Date(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        # Named explicitly rather than inline unique=True on the column:
        # inline would let Postgres pick discharges_admission_id_key, while
        # the ORM's NAMING_CONVENTION renders uq_discharges_admission_id.
        # Two names for one constraint is how ORM and database drift.
        sa.UniqueConstraint("admission_id", name="uq_discharges_admission_id"),
        sa.CheckConstraint(
            "discharge_type IN ('discharged','dama','deceased','absconded','transferred')",
            name="ck_discharges_discharge_type",
        ),
    )
    # admission_id is already UNIQUE, which creates its own index — no
    # separate one needed under the §3 blanket FK-index rule.


def downgrade() -> None:
    op.drop_table("discharges")
    op.drop_index("ix_admissions_bed_id", table_name="admissions")
    op.drop_index("ix_admissions_ward_id", table_name="admissions")
    op.drop_index("ix_admissions_patient_id", table_name="admissions")
    op.drop_index("ix_admissions_visit_id", table_name="admissions")
    op.drop_table("admissions")
    op.drop_table("beds")
    op.drop_index("ix_wards_facility_id", table_name="wards")
    op.drop_index("ix_wards_department_id", table_name="wards")
    op.drop_table("wards")

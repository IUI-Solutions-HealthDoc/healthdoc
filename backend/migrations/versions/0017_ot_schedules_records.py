<<<<<<< HEAD

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0017"
down_revision = "0015"  # placeholder — update to "0016" once blood_bank merges
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- ot_schedules -----------------------------------------------
    op.create_table(
        "ot_schedules",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "visit_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("visits.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("procedure_name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(50),  # enum-backed column -> varchar(50) blanket rule
            nullable=False,
            server_default="scheduled",
        ),
        # [Blame]
        sa.Column(
            "created_by",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('scheduled','completed','cancelled')",
            name="ck_ot_schedules_status",
        ),
    )
    op.create_index("ix_ot_schedules_visit_id", "ot_schedules", ["visit_id"])
    op.create_index("ix_ot_schedules_patient_id", "ot_schedules", ["patient_id"])
    op.create_index("ix_ot_schedules_created_by", "ot_schedules", ["created_by"])
    op.create_index("ix_ot_schedules_updated_by", "ot_schedules", ["updated_by"])

    # ---- ot_records ---------------------------------------------------
    op.create_table(
        "ot_records",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "ot_schedule_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("ot_schedules.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "surgeon_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "anesthetist_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        # No [Blame] tag on this table in §3 -- created_at/updated_at only
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_ot_records_ot_schedule_id", "ot_records", ["ot_schedule_id"]
    )
    op.create_index(
        "ix_ot_records_surgeon_user_id", "ot_records", ["surgeon_user_id"]
    )
    op.create_index(
        "ix_ot_records_anesthetist_user_id", "ot_records", ["anesthetist_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_ot_records_anesthetist_user_id", table_name="ot_records")
    op.drop_index("ix_ot_records_surgeon_user_id", table_name="ot_records")
    op.drop_index("ix_ot_records_ot_schedule_id", table_name="ot_records")
    op.drop_table("ot_records")

    op.drop_index("ix_ot_schedules_updated_by", table_name="ot_schedules")
    op.drop_index("ix_ot_schedules_created_by", table_name="ot_schedules")
    op.drop_index("ix_ot_schedules_patient_id", table_name="ot_schedules")
    op.drop_index("ix_ot_schedules_visit_id", table_name="ot_schedules")
=======
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- ot_schedules -----------------------------------------------
    op.create_table(
        "ot_schedules",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "visit_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("visits.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "facility_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("facilities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("procedure_name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(50),  # enum-backed column -> varchar(50) blanket rule
            nullable=False,
            server_default="scheduled",
        ),
        # [Blame]
        sa.Column(
            "created_by",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('scheduled','completed','cancelled')",
            name="ck_ot_schedules_status",
        ),
        sa.CheckConstraint(
            "scheduled_end > scheduled_start",
            name="ck_ot_schedules_time_order",
        ),
    )
    op.create_index("ix_ot_schedules_visit_id", "ot_schedules", ["visit_id"])
    op.create_index("ix_ot_schedules_patient_id", "ot_schedules", ["patient_id"])
    op.create_index("ix_ot_schedules_facility_id", "ot_schedules", ["facility_id"])
    op.create_index("ix_ot_schedules_created_by", "ot_schedules", ["created_by"])
    op.create_index("ix_ot_schedules_updated_by", "ot_schedules", ["updated_by"])

    # ---- ot_records ---------------------------------------------------
    op.create_table(
        "ot_records",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "ot_schedule_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("ot_schedules.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "surgeon_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "anesthetist_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        # No [Blame] tag on this table in §3 -- created_at/updated_at only
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR ended_at IS NULL OR ended_at > started_at",
            name="ck_ot_records_time_order",
        ),
    )
    op.create_index(
        "ix_ot_records_ot_schedule_id", "ot_records", ["ot_schedule_id"]
    )
    op.create_index(
        "ix_ot_records_surgeon_user_id", "ot_records", ["surgeon_user_id"]
    )
    op.create_index(
        "ix_ot_records_anesthetist_user_id", "ot_records", ["anesthetist_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_ot_records_anesthetist_user_id", table_name="ot_records")
    op.drop_index("ix_ot_records_surgeon_user_id", table_name="ot_records")
    op.drop_index("ix_ot_records_ot_schedule_id", table_name="ot_records")
    op.drop_table("ot_records")

    op.drop_index("ix_ot_schedules_updated_by", table_name="ot_schedules")
    op.drop_index("ix_ot_schedules_created_by", table_name="ot_schedules")
    op.drop_index("ix_ot_schedules_facility_id", table_name="ot_schedules")
    op.drop_index("ix_ot_schedules_patient_id", table_name="ot_schedules")
    op.drop_index("ix_ot_schedules_visit_id", table_name="ot_schedules")
>>>>>>> 2eaaabd (0017: fix down_revision, add facility_id + time-order checks, guard tests, register in env.py)
    op.drop_table("ot_schedules")
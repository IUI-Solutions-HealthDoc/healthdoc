"""Migration 0018 — B3-W3-01. Vitals table + SOAP note columns on encounters.

Adds:
  - vitals table (many-per-encounter, recorded over time)
  - subjective / objective / assessment / plan columns on encounters (1:1 SOAP note)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0018"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vitals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "encounter_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("encounters.id"),
            nullable=False,
        ),
        sa.Column("bp_systolic", sa.Integer(), nullable=True),
        sa.Column("bp_diastolic", sa.Integer(), nullable=True),
        sa.Column("pulse", sa.Integer(), nullable=True),
        sa.Column("temperature", sa.Numeric(4, 1), nullable=True),
        sa.Column("spo2", sa.Integer(), nullable=True),
        sa.Column("respiratory_rate", sa.Integer(), nullable=True),
        sa.Column("weight", sa.Numeric(5, 2), nullable=True),
        sa.Column("height", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "recorded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
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
        sa.CheckConstraint("spo2 IS NULL OR (spo2 >= 0 AND spo2 <= 100)", name="ck_vitals_spo2_range"),
    )
    op.create_index("ix_vitals_encounter_id", "vitals", ["encounter_id"])

    op.add_column("encounters", sa.Column("subjective", sa.Text(), nullable=True))
    op.add_column("encounters", sa.Column("objective", sa.Text(), nullable=True))
    op.add_column("encounters", sa.Column("assessment", sa.Text(), nullable=True))
    op.add_column("encounters", sa.Column("plan", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("encounters", "plan")
    op.drop_column("encounters", "assessment")
    op.drop_column("encounters", "objective")
    op.drop_column("encounters", "subjective")

    op.drop_index("ix_vitals_encounter_id", table_name="vitals")
    op.drop_table("vitals")

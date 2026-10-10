"""Control room disease trends: patients per diagnosis code per facility per day.

Revision ID: 0099
Revises: 0098
Create Date: 2026-10-10

Written by the 15-minute capture for the facility's today and yesterday, so a
late-coded diagnosis is still counted. A case is a distinct patient given a
provisional or final diagnosis that day; differentials are not cases. The
label comes from icd_codes, never from the clinician's free text, which may
hold anything. Small counts are suppressed when read, not here: the rollup is
an input to the trend, and the officer never reads it directly.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0099"
down_revision = "0098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagnosis_daily_counts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "facility_id",
            UUID(as_uuid=True),
            sa.ForeignKey("facilities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("icd_version", sa.String(30), nullable=False),
        sa.Column("icd_code", sa.String(30), nullable=False),
        sa.Column("patients", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("facility_id", "day", "icd_version", "icd_code", name="uq_diagnosis_daily_counts"),
        sa.CheckConstraint("patients > 0", name="ck_diagnosis_daily_counts_patients"),
    )
    op.create_index("ix_diagnosis_daily_counts_day", "diagnosis_daily_counts", ["day"])


def downgrade() -> None:
    op.drop_table("diagnosis_daily_counts")

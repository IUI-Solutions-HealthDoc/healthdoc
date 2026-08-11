"""doctor_reviews — review/sign-off on encounters and lab/radiology results

Revision ID: 0038
Revises: 0020c
Create Date: 2026-08-11

PROVISIONAL NUMBER: staging head is 0020c at time of writing. #351 (0021)
and #352 (0022) are pending merge; multiple other branches claim
0023-0037 (unmerged). 0038 chosen as the first number not claimed by any
open branch as of this scan — see PR description for the branch scan
this was based on. May need renumbering before merge; ping before
merging if staging has moved.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0038"
down_revision = "0020c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "doctor_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("lab_order_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lab_order_items.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("radiology_order_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("radiology_order_items.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("signed_off_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_check_constraint(
        "ck_doctor_reviews_status",
        "doctor_reviews",
        "status IN ('pending', 'reviewed', 'signed_off')",
    )

    op.create_index("ix_doctor_reviews_encounter_id", "doctor_reviews", ["encounter_id"])
    op.create_index("ix_doctor_reviews_reviewed_by", "doctor_reviews", ["reviewed_by"])
    op.create_index("ix_doctor_reviews_lab_order_item_id", "doctor_reviews", ["lab_order_item_id"])
    op.create_index("ix_doctor_reviews_radiology_order_item_id", "doctor_reviews", ["radiology_order_item_id"])
    op.create_index("ix_doctor_reviews_created_by", "doctor_reviews", ["created_by"])
    op.create_index("ix_doctor_reviews_updated_by", "doctor_reviews", ["updated_by"])


def downgrade() -> None:
    op.drop_index("ix_doctor_reviews_updated_by", table_name="doctor_reviews")
    op.drop_index("ix_doctor_reviews_created_by", table_name="doctor_reviews")
    op.drop_index("ix_doctor_reviews_radiology_order_item_id", table_name="doctor_reviews")
    op.drop_index("ix_doctor_reviews_lab_order_item_id", table_name="doctor_reviews")
    op.drop_index("ix_doctor_reviews_reviewed_by", table_name="doctor_reviews")
    op.drop_index("ix_doctor_reviews_encounter_id", table_name="doctor_reviews")
    op.drop_constraint("ck_doctor_reviews_status", "doctor_reviews", type_="check")
    op.drop_table("doctor_reviews")

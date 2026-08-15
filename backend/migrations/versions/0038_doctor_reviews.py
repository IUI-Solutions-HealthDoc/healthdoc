"""doctor_reviews — review/sign-off on encounters and lab/radiology results

Revision ID: 0038
Revises: 0036
Create Date: 2026-08-11

down_revision corrected twice during review on #361:
  1. Originally chained off 0031 (a real, already-merged migration) as a
     placeholder while its true parent was still unmerged; that
     placeholder forked the chain the moment 0032-0034 also merged onto
     0031 via staging (alembic heads showed both 0034 and 0038 as heads).
  2. Fixed to 0037 (Priyanshu's prescriptions.facility_id work, #353) and
     parked in pending/ since 0037 didn't exist in versions/ yet. 0037
     turned out to be broken (renamed constraints to names 0006 had
     already given them, failing on a fresh database) and was dropped;
     the surviving, merged migrations from that work are 0035
     (patients_row_version) and 0036 (patient_merge_log_decision_reason).
     down_revision corrected to 0036, the new real chain tip -- reviewer's
     note: "revision ids are opaque labels, so 0038 chaining off 0036 is
     fine and nobody has to renumber."

Moved back from pending/ to versions/ now that 0036 exists there --
see pending/README.md "Moving one back".
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0038"
down_revision = "0036a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "doctor_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
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
    op.create_index("ix_doctor_reviews_facility_id", "doctor_reviews", ["facility_id"])
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
    op.drop_index("ix_doctor_reviews_facility_id", table_name="doctor_reviews")
    op.drop_index("ix_doctor_reviews_encounter_id", table_name="doctor_reviews")
    op.drop_constraint("ck_doctor_reviews_status", "doctor_reviews", type_="check")
    op.drop_table("doctor_reviews")

"""0034 IPD bed integrity — one active admission per bed, and a transfer destination.

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-03

Schema v3.14 §3 0034.

One-active-admission-per-bed was left to the service layer. One bug there double-books a
bed, and the second admission looks perfectly valid — nothing in the data says otherwise.
A partial unique index removes the race rather than asking every future service method to
remember to handle it.

Same pattern already used by `uq_pharmacy_dispenses_current`.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Defensive: if the service layer has already double-booked in a running
    # deployment, CREATE UNIQUE INDEX fails with a duplicate-key error and the
    # migration aborts — correct, but opaque at 2am. Surface it as a readable
    # error naming the beds instead.
    # ------------------------------------------------------------------
    conn = op.get_bind()
    dupes = conn.execute(sa.text("""
        SELECT bed_id, count(*) AS n
        FROM admissions
        WHERE status = 'admitted'
        GROUP BY bed_id
        HAVING count(*) > 1
    """)).fetchall()
    if dupes:
        listed = ", ".join(f"{row[0]} ({row[1]} active admissions)" for row in dupes)
        raise RuntimeError(
            "Cannot enforce one-active-admission-per-bed: these beds are already "
            f"double-booked and must be resolved by hand first — {listed}. "
            "Discharge or transfer the stale admission, then re-run this migration."
        )

    op.create_index(
        "uq_admissions_active_bed", "admissions", ["bed_id"],
        unique=True, postgresql_where=sa.text("status = 'admitted'"),
    )

    # ------------------------------------------------------------------
    # A `transferred` discharge previously recorded no destination, so a patient
    # left the system with no forward reference — the one case where the next
    # clinician most needs to know where the record continues.
    #
    # Two columns because both cases are real: transfer to another facility we run
    # (FK), and transfer to one we do not (free text).
    # ------------------------------------------------------------------
    op.add_column(
        "discharges",
        sa.Column("destination_facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=True),
    )
    op.add_column(
        "discharges",
        sa.Column("destination_facility_name", sa.Text(), nullable=True),
    )
    op.create_index("ix_discharges_destination_facility_id", "discharges",
                    ["destination_facility_id"])

    op.create_check_constraint(
        "ck_discharges_transfer_destination",
        "discharges",
        "discharge_type <> 'transferred' "
        "OR destination_facility_id IS NOT NULL "
        "OR destination_facility_name IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_discharges_transfer_destination", "discharges", type_="check")
    op.drop_index("ix_discharges_destination_facility_id", table_name="discharges")
    op.drop_column("discharges", "destination_facility_name")
    op.drop_column("discharges", "destination_facility_id")
    op.drop_index("uq_admissions_active_bed", table_name="admissions")

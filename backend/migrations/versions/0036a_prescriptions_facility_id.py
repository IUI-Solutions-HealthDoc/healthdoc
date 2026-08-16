"""0036a prescriptions.facility_id

Revision ID: 0036a
Revises: 0036
Create Date: 2026-08-14

app/orders/models.py declares Prescription.facility_id as NOT NULL with an FK
to facilities, and sets __audit_facility_id_field__ = "facility_id" so the
auto-audit listener reads it. 0008 created the prescriptions table without the
column, and nothing since added it.

It stayed invisible because nothing inserted a prescription through the ORM.
The pharmacy tests write the table with raw SQL and omit the column, which
works. The first code to call db.add(Prescription(...)) gets UndefinedColumn.

Three PRs hit it at once: #361 added facility_id to the pharmacy test seed to
match the model, and #374/#375 are the first service code to construct the ORM
object.

OUT-OF-BAND NUMBER
------------------
0036a rather than the next free integer because 0038 (doctor_reviews, #361) is
already written and #361 is one of the PRs blocked by this — a migration that
chains *after* 0038 cannot unblock it. Inserting at 0036a keeps every claimed
number intact and costs #361 a one-line down_revision change.

Not 0037: that number was burned by a migration dropped during review (it
renamed constraints to names 0006 had already given them and failed on a fresh
database). Reusing it would make the history confusing to read.

BACKFILL
--------
From encounters.facility_id, which exists since 0021 and is NOT NULL, via
prescriptions.encounter_id, which is NOT NULL since 0008. So every existing row
resolves and SET NOT NULL is safe. Same shape as 0022's orders.facility_id.

Denormalized deliberately, like orders.facility_id: the audit layer opts a model
in via __audit_facility_id_field__ and needs the column on the row itself.
Reaching through encounter_id would make every audited write a join.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0036a"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "prescriptions",
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.execute(
        """
        UPDATE prescriptions AS p
           SET facility_id = e.facility_id
          FROM encounters AS e
         WHERE e.id = p.encounter_id
           AND p.facility_id IS NULL
        """
    )

    # Fails loudly if any row is left unresolved. encounters.facility_id is
    # NOT NULL and prescriptions.encounter_id is NOT NULL, so a survivor would
    # mean a broken FK, which is worth stopping for rather than tolerating.
    op.alter_column("prescriptions", "facility_id", nullable=False)

    op.create_foreign_key(
        "fk_prescriptions_facility_id",
        "prescriptions", "facilities",
        ["facility_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("ix_prescriptions_facility_id", "prescriptions", ["facility_id"])


def downgrade() -> None:
    op.drop_index("ix_prescriptions_facility_id", table_name="prescriptions")
    op.drop_constraint("fk_prescriptions_facility_id", "prescriptions", type_="foreignkey")
    op.drop_column("prescriptions", "facility_id")

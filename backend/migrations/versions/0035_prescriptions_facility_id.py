"""prescriptions.facility_id — backfill + NOT NULL + FK

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-14

prescriptions.facility_id was declared nullable=False with an FK to
facilities in app/orders/models.py, but no migration since 0008 ever
added the column. db.add(Prescription(...)) raises UndefinedColumn
against real Postgres — ORM tests pass only because they build schema
from Base.metadata instead of running migrations.

Same shape as 0022's orders.facility_id backfill: add nullable, backfill
from encounters.facility_id (present since 0021), set NOT NULL, then add
the FK + index.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "prescriptions",
        sa.Column("facility_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.execute(
        """
        UPDATE prescriptions p
        SET facility_id = e.facility_id
        FROM encounters e
        WHERE p.encounter_id = e.id
          AND p.facility_id IS NULL
        """
    )

    op.execute(
        """
        DO $$
        DECLARE
            missing_count integer;
        BEGIN
            SELECT count(*) INTO missing_count
            FROM prescriptions
            WHERE facility_id IS NULL;

            IF missing_count > 0 THEN
                RAISE EXCEPTION
                    '% prescriptions could not be backfilled with facility_id — encounter_id likely orphaned',
                    missing_count;
            END IF;
        END $$;
        """
    )

    op.alter_column("prescriptions", "facility_id", nullable=False)

    op.create_foreign_key(
        "fk_prescriptions_facility_id_facilities",
        "prescriptions",
        "facilities",
        ["facility_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_prescriptions_facility_id",
        "prescriptions",
        ["facility_id"],
    )


def downgrade():
    op.drop_index("ix_prescriptions_facility_id", table_name="prescriptions")
    op.drop_constraint(
        "fk_prescriptions_facility_id_facilities",
        "prescriptions",
        type_="foreignkey",
    )
    op.drop_column("prescriptions", "facility_id")

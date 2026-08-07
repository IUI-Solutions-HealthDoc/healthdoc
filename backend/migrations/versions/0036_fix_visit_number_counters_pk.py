"""fix visit_number_counters PK per §1 rule 1

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-03

WHY: schema doc §1 rule 1 -- "The primary key of every table is id
UUID... never anything else." visit_number_counters (migration 0025)
was built with PRIMARY KEY (facility_id, counter_date), a composite
business key, with no id column at all. This migration corrects that
without dropping the table, since it already holds live data.

Constraint name confirmed via inspect().get_pk_constraint() on
2026-08-03: pk_visit_number_counters (project naming convention from
app/common/db.py NAMING_CONVENTION), not Postgres's raw default.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "visit_number_counters",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("uuid_generate_v4()"),
        ),
    )

    op.drop_constraint(
        "pk_visit_number_counters", "visit_number_counters", type_="primary"
    )

    op.create_primary_key(
        "pk_visit_number_counters", "visit_number_counters", ["id"]
    )

    op.create_unique_constraint(
        "uq_visit_number_counters_facility_id_counter_date",
        "visit_number_counters",
        ["facility_id", "counter_date"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_visit_number_counters_facility_id_counter_date",
        "visit_number_counters",
        type_="unique",
    )
    op.drop_constraint(
        "pk_visit_number_counters", "visit_number_counters", type_="primary"
    )
    op.create_primary_key(
        "pk_visit_number_counters",
        "visit_number_counters",
        ["facility_id", "counter_date"],
    )
    op.drop_column("visit_number_counters", "id")

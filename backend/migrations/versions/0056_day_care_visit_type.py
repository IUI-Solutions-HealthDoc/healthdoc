"""0056 day_care visit type.

Revision ID: 0056
Revises: 0055
Create Date: 2026-09-01

Adds `day_care` to the visits.visit_type CHECK constraint.

WHY A SEPARATE TYPE RATHER THAN A FLAG ON IPD

A day-care patient occupies a real bed and is discharged the same day —
endoscopy, dialysis, chemotherapy, minor procedures. Ward occupancy has to
count them, which is why it is not an OPD sub-type. But length of stay, tariff
basis and discharge expectations all differ from an inpatient admission, and
folding them into `ipd` would make "how many inpatients do we have" — a number
every ward round and every bed-management report depends on — unanswerable
without a second qualifier nobody would remember to apply.

WHY THE CONSTRAINT IS REPLACED RATHER THAN DROPPED

Dropping it and adding it back leaves a window where any string is accepted.
Postgres cannot ALTER a CHECK in place, so the two statements are wrapped in
the migration's own transaction: either both apply or neither does. The
downgrade refuses to run while day_care rows exist rather than silently
violating the narrower constraint it is about to install.
"""
import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

_OLD = "'opd'::character varying, 'ipd'::character varying, 'emergency'::character varying, 'teleconsult'::character varying"
_NEW = _OLD.replace(
    "'ipd'::character varying,",
    "'ipd'::character varying, 'day_care'::character varying,",
)
#: The literal name in the database. Alembic's naming convention would build
#: "ck_visits_ck_visits_visit_type" from a bare label and prefix it a second
#: time, so raw SQL is used below rather than op.drop_constraint.
_CONSTRAINT = "ck_visits_ck_visits_visit_type"


def upgrade() -> None:
    op.execute(f'ALTER TABLE visits DROP CONSTRAINT "{_CONSTRAINT}"')
    op.execute(
        f'ALTER TABLE visits ADD CONSTRAINT "{_CONSTRAINT}" '
        f"CHECK ((visit_type)::text = ANY ((ARRAY[{_NEW}])::text[]))"
    )


def downgrade() -> None:
    # Refuse rather than corrupt. Narrowing a CHECK under rows that violate it
    # fails at VALIDATE with an error naming the constraint, not the data —
    # so this checks first and says which rows are in the way.
    remaining = op.get_bind().execute(
        sa.text("SELECT count(*) FROM visits WHERE visit_type = 'day_care'")
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} visit(s) still have visit_type='day_care'. Reassign or "
            "cancel them before downgrading; this migration will not silently "
            "leave rows that violate the constraint it is restoring."
        )
    op.execute(f'ALTER TABLE visits DROP CONSTRAINT "{_CONSTRAINT}"')
    op.execute(
        f'ALTER TABLE visits ADD CONSTRAINT "{_CONSTRAINT}" '
        f"CHECK ((visit_type)::text = ANY ((ARRAY[{_OLD}])::text[]))"
    )

"""Constrain nursing_handover_notes.shift to the three real shifts.

0050 created the table as part of a schema wave and nothing was ever built on
top of it: no ORM model, no service, no route. The frontend's AddHandoverForm
and HandoverNotes were written against an API that was never published, so a
ward could not record a shift handover at all.

The column went in as a bare varchar(30). Every other enumerated column in this
schema is varchar + CHECK using CheckedEnum.sql_check() (see
app/common/enums.py), and without it the database would accept "Morning",
"nite" or "" while the API accepted only three values — a divergence that shows
up as unqueryable data long after it is written, because the whole point of
naming the shift is being able to ask who held a patient on nights.

Safe to apply: the table is empty (nothing could write to it), so no existing
row can violate the new CHECK.
"""

from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None

_CHECK = "shift IN ('morning', 'evening', 'night')"


def upgrade() -> None:
    op.create_check_constraint("shift", "nursing_handover_notes", _CHECK)


def downgrade() -> None:
    op.drop_constraint("shift", "nursing_handover_notes", type_="check")

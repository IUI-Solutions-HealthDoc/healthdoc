"""UUID primary-key defaults and the visit status values the code writes.

Revision ID: 0089
Revises: 0088
Create Date: 2026-09-28

WHY THE DEFAULTS
    Migrations 0074-0076 created seven tables whose `id` has no server default,
    while their models inherit `UUIDPk`, which omits the id from the INSERT and
    relies on `uuid_generate_v4()`. On PostgreSQL every such insert failed with
    a NOT NULL violation: no appointment could be booked. The SQLite fixture
    builds tables from the models, which carry the default, so the suite passed.
    `abdm_callback_receipts` is not included: its model assigns ids itself.

WHY THE STATUS CHECK IS WIDENED
    0007 allowed only its own status vocabulary. The OPD state machine and the
    stale-visit reconciliation write `in_consultation` and `closed`, which that
    CHECK rejects, so the consultation transition failed with a 500. The new
    CHECK is the union of the 0007 values and the ones the code writes; nothing
    that was valid before becomes invalid.
"""

import sqlalchemy as sa
from alembic import op

revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None

_TABLES = (
    "appointment_services",
    "appointments",
    "clinical_dispositions",
    "admission_checklist_tasks",
    "emergency_triages",
    "emergency_triage_logs",
    "lab_analytes",
)

#: Literal database name; Alembic's naming convention would prefix a bare label again.
_STATUS_CONSTRAINT = "ck_visits_ck_visits_status"

_OLD_STATUSES = (
    "registered",
    "payment_pending",
    "waiting",
    "in_service",
    "waiting_for_investigation",
    "report_ready",
    "doctor_review_pending",
    "pharmacy_pending",
    "completed",
    "cancelled",
    "lwbs",
)
_ADDED_STATUSES = ("in_consultation", "closed")


def _status_check(values: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{v}'" for v in values)
    return f'ALTER TABLE visits ADD CONSTRAINT "{_STATUS_CONSTRAINT}" CHECK (status IN ({listed}))'


def upgrade() -> None:
    for table in _TABLES:
        op.alter_column(table, "id", server_default=sa.text("uuid_generate_v4()"))

    op.execute(f'ALTER TABLE visits DROP CONSTRAINT "{_STATUS_CONSTRAINT}"')
    op.execute(_status_check(_OLD_STATUSES + _ADDED_STATUSES))


def downgrade() -> None:
    remaining = op.get_bind().execute(
        sa.text("SELECT count(*) FROM visits WHERE status IN ('in_consultation', 'closed')")
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} visit(s) have status in_consultation or closed. Move them to a "
            "status the 0007 constraint allows before downgrading; this migration will "
            "not leave rows that violate the constraint it is restoring."
        )
    op.execute(f'ALTER TABLE visits DROP CONSTRAINT "{_STATUS_CONSTRAINT}"')
    op.execute(_status_check(_OLD_STATUSES))

    for table in _TABLES:
        op.alter_column(table, "id", server_default=None)

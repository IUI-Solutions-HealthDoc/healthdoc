"""0039 notification_history.facility_id

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-11

notification_history had event_type, payload and a nullable department_id, and
no facility column at all. A row whose department_id is NULL could not be
attributed to a facility, and no read query could be scoped to one.

Nothing reads the table yet — app/notifications/router.py is a /ping stub — so
nothing has leaked. The fix lands now because #230 (notification history API)
is assigned and unstarted, and the first SELECT written against this table
either scopes by facility or serves every facility's notifications to every
reader. Adding the column after that endpoint exists means fixing an endpoint
as well as a table.

department_id stays nullable on purpose. A facility-wide announcement has a
facility and no department; a queue event has both. Making department_id NOT
NULL would rule out the first case. facility_id is NOT NULL because there is
no notification that belongs to no facility.

The backfill has to fight 0020's append-only trigger, which raises on UPDATE.
It comes off, the backfill runs, it goes back on. SET NOT NULL is deliberately
the last step and is deliberately not defensive: if any row survives the
backfill with a NULL facility_id, that means a notification exists that cannot
be attributed to a facility, and this migration should fail loudly rather than
leave the column nullable and the question open.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The trigger raises on UPDATE, and the backfill below is an UPDATE.
    op.execute(
        "DROP TRIGGER IF EXISTS trg_notification_history_block_update "
        "ON notification_history"
    )

    op.add_column(
        "notification_history",
        sa.Column("facility_id", UUID(as_uuid=True), nullable=True),
    )

    # Every existing row was written by the queue or pathology path, and both
    # set department_id, so departments is a complete source for them.
    op.execute(
        """
        UPDATE notification_history AS n
           SET facility_id = d.facility_id
          FROM departments AS d
         WHERE d.id = n.department_id
           AND n.facility_id IS NULL
        """
    )

    # Fails if anything is left NULL. That is the intent: an unattributable
    # notification is a bug to surface, not a NULL to tolerate.
    op.alter_column("notification_history", "facility_id", nullable=False)

    op.create_foreign_key(
        "fk_notification_history_facility_id",
        "notification_history", "facilities",
        ["facility_id"], ["id"], ondelete="RESTRICT",
    )
    # (facility_id, created_at): every read of this table is "recent
    # notifications for my facility", which is what #230 will ask for.
    op.create_index(
        "ix_notification_history_facility_id_created_at",
        "notification_history", ["facility_id", "created_at"],
    )

    op.execute(
        """
        CREATE TRIGGER trg_notification_history_block_update
        BEFORE UPDATE OR DELETE ON notification_history
        FOR EACH ROW EXECUTE FUNCTION trg_notification_history_block_update()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_notification_history_block_update "
        "ON notification_history"
    )
    op.drop_index(
        "ix_notification_history_facility_id_created_at",
        table_name="notification_history",
    )
    op.drop_constraint(
        "fk_notification_history_facility_id",
        "notification_history", type_="foreignkey",
    )
    op.drop_column("notification_history", "facility_id")
    op.execute(
        """
        CREATE TRIGGER trg_notification_history_block_update
        BEFORE UPDATE OR DELETE ON notification_history
        FOR EACH ROW EXECUTE FUNCTION trg_notification_history_block_update()
        """
    )

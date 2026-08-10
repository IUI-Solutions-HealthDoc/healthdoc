"""Migration 0003a — facilities fixes (post-merge corrections to 0002).

Corrects three deviations found after 0002 was merged to staging:

A. facilities.timezone — missing column required by the business-date rule:
   (now() AT TIME ZONE facilities.timezone)::date
   Billing MIS, queue counters, bed-day accrual, accession numbers all depend on it.
   Without it, anything computing a business date in UTC is wrong by 5h30m in IST.

B. idempotency_keys — table listed under 0002 in §2 but never created.
   Billing service reads/writes it (app/billing/service.py, idempotency_keys_t).
   Includes endpoint + request_hash so a corrected retry returns 409 instead of
   silently replaying the stale response.

C. facilities.facility_type — varchar(30) should be varchar(50) per blanket rule.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0003a"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A. Add timezone column to facilities
    op.add_column("facilities", sa.Column(
        "timezone", sa.String(50), nullable=False, server_default="Asia/Kolkata"))

    # B. Create idempotency_keys table
    op.create_table(
        "idempotency_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE",
                                name="fk_idempotency_keys_user_id"),
                  nullable=False),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.SmallInteger(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now() + interval '24 hours'")),
        sa.UniqueConstraint("key", "user_id", "endpoint",
                            name="uq_idempotency_keys_key_user_endpoint"),
    )
    op.create_index("ix_idempotency_keys_user_id",
                     "idempotency_keys", ["user_id"])
    op.create_index("ix_idempotency_keys_expires_at",
                     "idempotency_keys", ["expires_at"])

    # C. Widen facility_type from varchar(30) to varchar(50)
    op.alter_column("facilities", "facility_type",
                     type_=sa.String(50), existing_type=sa.String(30))


def downgrade() -> None:
    # C. Revert facility_type width
    op.alter_column("facilities", "facility_type",
                     type_=sa.String(30), existing_type=sa.String(50))

    # B. Drop idempotency_keys
    op.drop_index("ix_idempotency_keys_expires_at", table_name="idempotency_keys")
    op.drop_index("ix_idempotency_keys_user_id", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")

    # A. Drop timezone column
    op.drop_column("facilities", "timezone")

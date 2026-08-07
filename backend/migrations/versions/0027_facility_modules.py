"""Migration 0027 — facility_modules + orders.fulfilment_mode (B1).

Per-facility module toggles (pharmacy, lab, radiology, etc.) and the
fulfilment_mode column on orders. Blocking other people's PRs that use
require_module() — this table must exist before any optional module
can be toggled.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "facility_modules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="CASCADE",
                                name="fk_facility_modules_facility_id"),
                  nullable=False),
        sa.Column("module_code", sa.String(50), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("facility_id", "module_code",
                            name="uq_facility_modules_facility_id_module_code"),
        sa.CheckConstraint(
            "module_code IN ('lab','radiology','pharmacy','ot','blood_bank')",
            name="ck_facility_modules_module_code",
        ),
    )
    op.create_index("ix_facility_modules_facility_id",
                     "facility_modules", ["facility_id"])

    op.add_column(
        "orders",
        sa.Column("fulfilment_mode", sa.String(50), nullable=False, server_default="internal"),
    )
    op.create_check_constraint(
        "ck_orders_fulfilment_mode",
        "orders",
        "fulfilment_mode IN ('internal', 'external_referral')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_fulfilment_mode", "orders", type_="check")
    op.drop_column("orders", "fulfilment_mode")
    op.drop_index("ix_facility_modules_facility_id", table_name="facility_modules")
    op.drop_table("facility_modules")

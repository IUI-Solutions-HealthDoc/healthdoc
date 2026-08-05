"""Migration 0027 — facility_modules + orders.fulfilment_mode (B1).

Per-facility module toggles (pharmacy, lab, radiology, etc.) and the
fulfilment_mode column on orders. Blocking other people's PRs that use
require_module() — this table must exist before any optional module
can be toggled.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0027"
# TODO: update to "0026" (or whatever the actual predecessor is) when rebasing onto staging.
# Set to "0002" here because 0003–0026 are other teams' migrations not in this folder.
down_revision = "0002"
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
        sa.Column("enabled_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("facility_id", "module_code",
                            name="uq_facility_modules_facility_id_module_code"),
        sa.CheckConstraint(
            "module_code IN ('lab','radiology','pharmacy','inventory','ipd','ot',"
            "'blood_bank','emergency','patient_portal','abdm','billing_refunds')",
            name="ck_facility_modules_module_code",
        ),
    )
    op.create_index("ix_facility_modules_facility_id",
                     "facility_modules", ["facility_id"])

    # orders.fulfilment_mode — internal | external_referral
    # This ALTER runs only if the orders table exists (it may come from another migration).
    # Using execute to be safe against table-not-yet-existing scenarios.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'orders') THEN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name = 'orders' AND column_name = 'fulfilment_mode') THEN
                    ALTER TABLE orders ADD COLUMN fulfilment_mode VARCHAR(50)
                        NOT NULL DEFAULT 'internal';
                    ALTER TABLE orders ADD CONSTRAINT ck_orders_fulfilment_mode
                        CHECK (fulfilment_mode IN ('internal', 'external_referral'));
                END IF;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'orders') THEN
                ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_orders_fulfilment_mode;
                ALTER TABLE orders DROP COLUMN IF EXISTS fulfilment_mode;
            END IF;
        END $$;
    """)
    op.drop_index("ix_facility_modules_facility_id", table_name="facility_modules")
    op.drop_table("facility_modules")

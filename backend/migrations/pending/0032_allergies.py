"""0032 allergies — patient allergy register + the ingredient key that makes it work.

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-03

Schema v3.14 §3 0032.

Why this table exists: before it, an allergy lived as free text in a consultation note,
so the prescribing screen had nothing structured to check a new medicine against. That
is the most common preventable medication harm in a hospital system.

The critical design point is `ingredient_code`. Matching an allergy on
`inventory_item_id` is useless — a patient allergic to penicillin must also trigger on
amoxicillin and cloxacillin, which are separate `inventory_items` rows. So the match is
on the ingredient (WHO ATC level-5 where available, local ingredient list otherwise),
and this migration adds that column to `inventory_items` too.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "allergies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("patient_id", UUID(as_uuid=True),
                  sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("allergen_type", sa.String(50), nullable=False),

        # substance_text is NOT NULL even when a code is present. Rural reality: the
        # attendant says "penicillin injection" and that sentence IS the record. Losing
        # it because we could not code it is the failure mode to avoid.
        sa.Column("substance_text", sa.Text(), nullable=False),

        # The matchable key. NULL is allowed and means "display-only" — the banner shows
        # it, but it can never block a prescription. The API must say so explicitly;
        # a silent non-match is worse than not having the feature.
        sa.Column("ingredient_code", sa.String(50), nullable=True),
        sa.Column("inventory_item_id", UUID(as_uuid=True), nullable=True),

        sa.Column("reaction", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("onset_date", sa.Date(), nullable=True),

        sa.Column("recorded_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("verified_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),

        sa.CheckConstraint(
            "allergen_type IN ('drug', 'food', 'environmental', 'other')",
            name="ck_allergies_allergen_type"),
        sa.CheckConstraint(
            "severity IN ('mild', 'moderate', 'severe', 'anaphylaxis')",
            name="ck_allergies_severity"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'refuted', 'entered_in_error')",
            name="ck_allergies_status"),
        # A verified allergy must say who verified it — half a signature is not one.
        sa.CheckConstraint(
            "(verified_by IS NULL) = (verified_at IS NULL)",
            name="ck_allergies_verification_complete"),
    )

    # The prescribing gate reads exactly this: active allergies for one patient.
    op.create_index("ix_allergies_patient_id_status", "allergies", ["patient_id", "status"])
    op.create_index(
        "ix_allergies_ingredient_code", "allergies", ["ingredient_code"],
        postgresql_where=sa.text("ingredient_code IS NOT NULL AND status = 'active'"),
    )

    # Deferred FK: inventory_items comes from 0012, which is later in dependency order
    # than patients but earlier than this migration, so the FK is safe to add here.
    op.add_column(
        "inventory_items",
        sa.Column("ingredient_code", sa.String(50), nullable=True),
    )
    op.create_index(
        "ix_inventory_items_ingredient_code", "inventory_items", ["ingredient_code"],
        postgresql_where=sa.text("ingredient_code IS NOT NULL"),
    )
    op.create_foreign_key(
        "fk_allergies_inventory_item_id", "allergies", "inventory_items",
        ["inventory_item_id"], ["id"],
    )

    # Allergy override trail on the prescription line. The reason is mandatory whenever
    # an override happened, and the length floor stops "ok" being a clinical rationale.
    op.add_column(
        "prescription_items",
        sa.Column("allergy_override_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "prescription_items",
        sa.Column("allergy_override_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
    )
    op.create_check_constraint(
        "ck_prescription_items_allergy_override",
        "prescription_items",
        "(allergy_override_reason IS NULL AND allergy_override_by IS NULL) "
        "OR (char_length(allergy_override_reason) >= 20 AND allergy_override_by IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_prescription_items_allergy_override", "prescription_items",
                       type_="check")
    op.drop_column("prescription_items", "allergy_override_by")
    op.drop_column("prescription_items", "allergy_override_reason")

    op.drop_constraint("fk_allergies_inventory_item_id", "allergies", type_="foreignkey")
    op.drop_index("ix_inventory_items_ingredient_code", table_name="inventory_items")
    op.drop_column("inventory_items", "ingredient_code")

    op.drop_index("ix_allergies_ingredient_code", table_name="allergies")
    op.drop_index("ix_allergies_patient_id_status", table_name="allergies")
    op.drop_table("allergies")

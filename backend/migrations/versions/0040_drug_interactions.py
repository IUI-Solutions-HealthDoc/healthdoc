"""0040 drug_interactions

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-16

Builds: drug_interactions (schema.md §3, 0040)

#381 declares the DrugInteraction ORM model and queries it from
find_interaction() on every dispense, but no migration ever created the table
— the branch carries an empty autogenerate stub (954768c4a0af, upgrade/
downgrade both `pass`) that was presumably meant to be this and never filled
in. Without it, the first dispense raises UndefinedTable.

CANONICAL PAIR ORDERING
-----------------------
An interaction between A and B is one fact, not two. Storing it twice invites
the pair that only got inserted one way round, which then silently fails to
match. The CHECK enforces ingredient_code_a < ingredient_code_b, and
find_interaction() sorts before querying, so (A,B) and (B,A) resolve to the
same row by construction. The UNIQUE covers the ordered pair, so a duplicate
is rejected at the database rather than producing two rows that disagree.

is_active rather than deleting: an interaction rule that turns out to be wrong
should stop firing without erasing the record that it once did — a
prescription overridden last month was overridden against the rule as it stood
then, and the audit trail has to remain readable.

Constraint names are the bare form. NAMING_CONVENTION in common/db.py renders
ck_%(table_name)s_%(constraint_name)s, so passing "severity" here produces
ck_drug_interactions_severity. Passing the full name would produce
ck_drug_interactions_ck_drug_interactions_severity — the double-prefix bug
fixed across four constraints in #380.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drug_interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("ingredient_code_a", sa.String(50), nullable=False),
        sa.Column("ingredient_code_b", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        # No is_absolute column: the model derives it as a property from
        # severity == 'contraindicated', which is the right call — one source
        # of truth, and no way for the two to disagree.
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "severity IN ('contraindicated','major','moderate','minor')",
            name="ck_drug_interactions_severity",
        ),
        # One fact per pair. find_interaction() sorts the two codes before
        # querying, so this makes (A,B) and (B,A) the same row rather than a
        # rule that matches in only one direction.
        sa.CheckConstraint(
            "ingredient_code_a < ingredient_code_b",
            name="ck_drug_interactions_ordered_pair",
        ),
        # Unnamed in the ORM, so NAMING_CONVENTION renders
        # uq_%(table_name)s_%(column_0_N_name)s. Spelled out here so the
        # database matches what SQLAlchemy expects — a different name would
        # show up as drift and break autogenerate comparisons.
        sa.UniqueConstraint("ingredient_code_a", "ingredient_code_b",
                            name="uq_drug_interactions_ingredient_code_a_ingredient_code_b"),
    )
    # Index names match the ORM's explicit Index(...) declarations exactly.
    # For ix/uq the convention builds from column names and an explicit name
    # is used verbatim, so these are what the model actually asks for.
    op.create_index("ix_drug_interactions_a", "drug_interactions", ["ingredient_code_a"])
    op.create_index("ix_drug_interactions_b", "drug_interactions", ["ingredient_code_b"])


def downgrade() -> None:
    op.drop_index("ix_drug_interactions_b", table_name="drug_interactions")
    op.drop_index("ix_drug_interactions_a", table_name="drug_interactions")
    op.drop_table("drug_interactions")

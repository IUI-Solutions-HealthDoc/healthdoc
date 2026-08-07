"""Migration 0029 — ABAC policy table (B1-W2-02).

Attribute-based access rules evaluated after RBAC. A policy grants/denies an
(action) on a (resource_type) for a (subject_role), optionally constrained by a
JSON condition matched against request attributes (facility, department, ownership).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("subject_role", sa.String(50), nullable=False),   # Keycloak realm role
        sa.Column("resource_type", sa.String(50), nullable=False),  # e.g. 'patients'
        sa.Column("action", sa.String(50), nullable=False),         # read|create|update|delete
        sa.Column("effect", sa.String(50), nullable=False, server_default="allow"),  # allow|deny
        sa.Column("condition", JSONB(), nullable=True),             # {"same_facility": true, ...}
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("effect IN ('allow','deny')", name="ck_policies_effect"),
        sa.CheckConstraint("action IN ('read','create','update','delete')", name="ck_policies_action"),
    )
    op.create_index("ix_policies_subject_role_resource_type_action", "policies",
                    ["subject_role", "resource_type", "action"])


def downgrade() -> None:
    op.drop_index("ix_policies_subject_role_resource_type_action", table_name="policies")
    op.drop_table("policies")

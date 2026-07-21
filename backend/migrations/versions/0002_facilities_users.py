"""Migration 0002 — facilities and users (B1).

users holds the app-side profile; credentials and roles live in Keycloak,
linked via keycloak_sub. department_id is added later by migration 0005.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "facilities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("state_code", sa.String(5), nullable=False),
        sa.Column("district", sa.Text()),
        sa.Column("facility_type", sa.String(30)),
        sa.Column("hfr_facility_id", sa.String(50)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_facilities_code"),
    )
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("keycloak_sub", sa.String(64), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("mobile", sa.String(20)),
        sa.Column("designation", sa.String(100)),
        sa.Column("employee_id", sa.String(30)),
        sa.Column("registration_number", sa.String(50)),
        sa.Column("qualification", sa.String(100)),
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT",
                                name="fk_users_facility_id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("keycloak_sub", name="uq_users_keycloak_sub"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("facility_id", "employee_id", name="uq_users_facility_id_employee_id"),
    )
    op.create_index("ix_users_facility_id", "users", ["facility_id"])


def downgrade() -> None:
    op.drop_index("ix_users_facility_id", table_name="users")
    op.drop_table("users")
    op.drop_table("facilities")

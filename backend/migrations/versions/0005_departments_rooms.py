"""Migration 0005 — departments, rooms."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        # not globally. Two hospitals can both have a "MED" department.
        sa.UniqueConstraint("facility_id", "code", name="uq_department_facility_code"),
    )

    op.create_index("ix_departments_facility_id", "departments", ["facility_id"])

    op.create_table(
        "rooms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("department_id", UUID(as_uuid=True),
                  sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("room_number", sa.String(30), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("department_id", "room_number", name="uq_room_per_department"),
    )

    op.add_column(
        "users",
        sa.Column("department_id", UUID(as_uuid=True), sa.ForeignKey("departments.id"), nullable=True),
    )
    op.create_index("ix_users_department_id", "users", ["department_id"])

    op.create_foreign_key(
        "fk_audit_logs_department_id", "audit_logs", "departments",
        ["department_id"], ["id"],
    )

def downgrade() -> None:
    op.drop_constraint("fk_audit_logs_department_id", "audit_logs", type_="foreignkey")
    op.drop_index("ix_users_department_id", table_name="users")
    op.drop_column("users", "department_id")
    op.drop_table("rooms")
    op.drop_index("ix_departments_facility_id", table_name="departments")
    op.drop_table("departments")

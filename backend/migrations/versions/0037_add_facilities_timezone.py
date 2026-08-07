"""add facilities.timezone

Revision ID: 0032
Revises: 0026
Create Date: 2026-08-03

NOTE ON NUMBERING: as of writing, alembic heads == 0026. Migrations
0027-0031 are already reserved in schema doc §2 for specific B1 tasks
(facility_modules, user_account_requests, policies, abha_linking_token,
outbox_events) but not yet built. This migration is numbered 0032 --
past that whole reserved block -- specifically to avoid colliding with
them. If any of 0027-0031 land and merge before this one does, REBASE
down_revision below to whatever the actual head is at merge time.

WHY THIS MIGRATION EXISTS: facilities.timezone is specified in §3-0002
of the schema doc but was never actually added -- confirmed via
migrations/versions/0002_*.py, no timezone column present.
"""
from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "facilities",
        sa.Column(
            "timezone",
            sa.String(length=50),
            nullable=False,
            server_default="Asia/Kolkata",
        ),
    )


def downgrade():
    op.drop_column("facilities", "timezone")

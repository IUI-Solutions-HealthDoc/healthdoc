"""0057 retain the verified ABHA address needed by M2/M3.

Revision ID: 0057
Revises: 0056
Create Date: 2026-09-02

The M1 gateway response carries both an ABHA number and a PHR/ABHA address.
Only the number was stored, but M2 discovery and M3 consent identify a patient
by the address. Dropping it made a successful M1 identity impossible to find
when the gateway called back.
"""

import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("abha_address", sa.String(120), nullable=True))
    op.create_unique_constraint("uq_patients_abha_address", "patients", ["abha_address"])


def downgrade() -> None:
    op.drop_constraint("uq_patients_abha_address", "patients", type_="unique")
    op.drop_column("patients", "abha_address")

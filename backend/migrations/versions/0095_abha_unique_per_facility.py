"""One ABHA per chart per facility, not per installation.

Revision ID: 0095
Revises: 0094
Create Date: 2026-10-06

patients.abha_number and abha_address were unique across the installation, so
a person linked at one facility could not be linked at another in the same
deployment: the desk was told "cannot be linked at this facility". Now that
each facility is its own HIP (integrations/abdm/facilities.py), that is wrong.
ABDM links one ABHA to every provider that treats the person, and a facility
fetching another's records as an HIU needs its own chart bound to the address
the consent names. Within a facility the address and number stay unique: a
second chart there is still a duplicate for the desk to resolve.

Downgrade refuses while one ABHA is linked at two facilities: restoring the
installation-wide constraint would fail, and unlinking either chart is a desk
decision, not a migration's.
"""

import sqlalchemy as sa
from alembic import op

revision = "0095"
down_revision = "0094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_patients_abha_number", "patients", type_="unique")
    op.drop_constraint("uq_patients_abha_address", "patients", type_="unique")
    op.create_unique_constraint(
        "uq_patients_facility_abha_number", "patients", ["facility_id", "abha_number"]
    )
    op.create_unique_constraint(
        "uq_patients_facility_abha_address", "patients", ["facility_id", "abha_address"]
    )


def downgrade() -> None:
    shared = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM ("
            " SELECT abha_number FROM patients WHERE abha_number IS NOT NULL"
            " GROUP BY abha_number HAVING count(*) > 1"
            " UNION ALL"
            " SELECT abha_address FROM patients WHERE abha_address IS NOT NULL"
            " GROUP BY abha_address HAVING count(*) > 1) AS shared"
        )
    )
    if shared:
        raise RuntimeError(
            f"{shared} ABHA number(s) or address(es) are linked at more than one facility. "
            "Unlink them at the desk before downgrading."
        )
    op.drop_constraint("uq_patients_facility_abha_address", "patients", type_="unique")
    op.drop_constraint("uq_patients_facility_abha_number", "patients", type_="unique")
    op.create_unique_constraint("uq_patients_abha_address", "patients", ["abha_address"])
    op.create_unique_constraint("uq_patients_abha_number", "patients", ["abha_number"])

"""0042 guardian_verification — the patients columns the ORM has always declared.

Revision ID: 0042
Revises: 0041c
Create Date: 2026-08-17

WHY THIS IS LATE
----------------
`app/patients/models.py` has declared `is_minor`, `guardian_verified` and
`guardian_verification_method` since B2-W3. No migration ever created them.
§2 reserved a number four separate times — 0036, then 0038, 0040, 0041, now
0042 — and each time ready work took the number while this stayed unwritten.

Nothing caught it because unit tests build their schema from `Base.metadata`,
which creates whatever the ORM declares. The columns therefore existed in every
test and in no database. It surfaced on #393, whose concurrency test is the
first to INSERT a patient through the ORM against a *migrated* database:

    asyncpg.exceptions.UndefinedColumnError:
    column "guardian_verification_method" of relation "patients" does not exist

Every `INSERT INTO patients` through the ORM has been broken against a real
database — the same failure mode as `visit_number_counters` in #383, and the
fourth ORM/migration drift found today.

WIDTH
-----
§3 specifies `varchar(30)`; the ORM had drifted to `String(50)`. Taking §3 as
authoritative and narrowing the model to match — the longest permitted value is
'manual_document' at 15 characters.

The CHECK mirrors `GuardianVerificationMethod`, which already existed in
`app/common/enums.py` and had nothing enforcing it.
"""
import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("is_minor", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "patients",
        sa.Column("guardian_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "patients",
        sa.Column("guardian_verification_method", sa.String(30), nullable=True),
    )

    # Healthcare exemptions to parental-consent rules still require
    # documentation; these columns are that evidence, so the method has to be
    # one of the three the DPDP guidance recognises rather than free text.
    op.create_check_constraint(
        "ck_patients_guardian_verification_method",
        "patients",
        "guardian_verification_method IS NULL OR guardian_verification_method IN "
        "('aadhaar','digilocker','manual_document')",
    )

    # NOT adding a "verified implies a method is recorded" constraint. It is not
    # in §3, and pairing state across two columns is a workflow rule rather than
    # a storage invariant — a clinician may record the method at one step and
    # confirm at another. Enforce it in the service layer if we want it.


def downgrade() -> None:
    op.drop_constraint("ck_patients_guardian_verification_method", "patients", type_="check")
    op.drop_column("patients", "guardian_verification_method")
    op.drop_column("patients", "guardian_verified")
    op.drop_column("patients", "is_minor")

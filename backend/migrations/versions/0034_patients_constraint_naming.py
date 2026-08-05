"""0034 constraint naming — PR review should-fix: check constraints across
patients, patient_identifiers, patient_merge_log used short names (e.g.
"sex", "status") that collide across tables and don't follow the
ck_<table>_<column> convention, causing Alembic autogenerate to want to
drop and recreate them on every run. Renamed in place — RENAME CONSTRAINT
is metadata-only in Postgres, no enforcement gap, no table rewrite.

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-05
"""
from alembic import op

revision = '0034'
down_revision = '0033'
branch_labels = None
depends_on = None

_RENAMES = [
    ("patients", "dob_or_age", "ck_patients_dob_or_age"),
    ("patients", "has_identifier", "ck_patients_has_identifier"),
    ("patients", "sex", "ck_patients_sex"),
    ("patients", "identity_path", "ck_patients_identity_path"),
    ("patients", "identity_status", "ck_patients_identity_status"),
    ("patients", "status", "ck_patients_status"),
    ("patient_identifiers", "identifier_type", "ck_patient_identifiers_identifier_type"),
    ("patient_merge_log", "source_type", "ck_patient_merge_log_source_type"),
    ("patient_merge_log", "status", "ck_patient_merge_log_status"),
]


def upgrade() -> None:
    for table, old_name, new_name in _RENAMES:
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old_name}" TO "{new_name}"')


def downgrade() -> None:
    for table, old_name, new_name in reversed(_RENAMES):
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{new_name}" TO "{old_name}"')

"""0006 patients

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-18 10:17:23.897391
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def _create_sequences_for_existing_facilities() -> None:
    """Called at the end of upgrade() — creates UHID sequences for all
    facilities that exist at deploy time so the registration endpoint
    never needs CREATE SEQUENCE in the request path."""
    import zoneinfo
    from datetime import datetime
    from sqlalchemy import text
    conn = op.get_bind()
    rows = conn.execute(
        text("SELECT code, timezone FROM facilities WHERE is_active = true")
    ).fetchall()
    for code, tz_name in rows:
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            tz = zoneinfo.ZoneInfo("Asia/Kolkata")
        year = datetime.now(tz).year
        safe_code = code.lower().replace("-", "_")
        seq_name = f"seq_uhid_{safe_code}_{year}"
        conn.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{seq_name}"'))



def upgrade() -> None:
    op.create_table('patients',
    sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
    sa.Column('uhid', sa.String(length=30), nullable=True),
    sa.Column('thid', sa.String(length=25), nullable=True),
    sa.Column('full_name', sa.Text(), nullable=False),
    sa.Column('sex', sa.String(length=50), nullable=False),
    sa.Column('dob', sa.Date(), nullable=True),
    sa.Column('age_years', sa.SmallInteger(), nullable=True),
    sa.Column('guardian_name', sa.Text(), nullable=True),
    sa.Column('guardian_relationship', sa.String(length=50), nullable=True),
    sa.Column('mobile', sa.String(length=20), nullable=True),
    sa.Column('address_line', sa.Text(), nullable=True),
    sa.Column('village_town', sa.Text(), nullable=True),
    sa.Column('district', sa.Text(), nullable=True),
    sa.Column('state_code', sa.String(length=5), nullable=True),
    sa.Column('pincode', sa.String(length=6), nullable=True),
    sa.Column('photo_file_id', sa.UUID(), nullable=True),
    sa.Column('abha_number', sa.String(length=17), nullable=True),
    sa.Column('identity_path', sa.String(length=50), nullable=False),
    sa.Column('identity_status', sa.String(length=50), server_default='verified', nullable=False),
    sa.Column('status', sa.String(length=50), server_default='active', nullable=False),
    sa.Column('merged_into_patient_id', sa.UUID(), nullable=True),
    sa.Column('facility_id', sa.UUID(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('dob IS NOT NULL OR age_years IS NOT NULL', name='ck_patients_dob_or_age'),
    sa.CheckConstraint('uhid IS NOT NULL OR thid IS NOT NULL', name='ck_patients_has_identifier'),
    sa.CheckConstraint("sex IN ('male', 'female', 'other', 'unknown')", name='ck_patients_sex'),
    sa.CheckConstraint("identity_path IN ('abdm', 'thid', 'aadhaar_mobile', 'demographics_only')", name='ck_patients_identity_path'),
    sa.CheckConstraint("identity_status IN ('verified', 'identity_unverified', 'photo_pending')", name='ck_patients_identity_status'),
    sa.CheckConstraint("status IN ('active', 'merged', 'deceased')", name='ck_patients_status'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['deleted_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
    sa.ForeignKeyConstraint(['merged_into_patient_id'], ['patients.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('abha_number'),
    # thid uniqueness = partial index, not a plain constraint, so a soft-deleted
    # row never permanently blocks reissuing that THID to a new emergency patient.
    # Mirrors the uhid partial index above — same reasoning, same fix (PR review).
    )
    # uhid uniqueness = partial index, not a plain constraint, so a soft-deleted
    # (deleted_at IS NOT NULL) row never blocks reissuing/correcting a UHID.
    op.create_index(
        'uq_patients_uhid', 'patients', ['uhid'],
        unique=True, postgresql_where=sa.text('deleted_at IS NULL'),
    )
    op.create_index(
        'uq_patients_thid', 'patients', ['thid'],
        unique=True, postgresql_where=sa.text('deleted_at IS NULL'),
    )
    op.create_index(
        'ix_patients_full_name_trgm', 'patients', ['full_name'],
        unique=False, postgresql_using='gin',
        postgresql_ops={'full_name': 'gin_trgm_ops'},
    )

    op.create_table('patient_identifiers',
    sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
    sa.Column('patient_id', sa.UUID(), nullable=False),
    sa.Column('identifier_type', sa.String(length=50), nullable=False),
    sa.Column('identifier_value_encrypted', sa.LargeBinary(), nullable=False),
    sa.Column('identifier_blind_index', sa.String(length=64), nullable=False),
    sa.Column('key_version', sa.SmallInteger(), server_default='1', nullable=False),
    sa.Column('verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('captured_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("identifier_type IN ('aadhaar', 'abha', 'voter_id', 'other')", name='ck_patient_identifiers_identifier_type'),
    sa.ForeignKeyConstraint(['captured_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('patient_id', 'identifier_type', name='uq_patient_identifier_type')
    )
    op.create_index(op.f('ix_patient_identifiers_identifier_blind_index'), 'patient_identifiers', ['identifier_blind_index'], unique=False)
    op.create_index(op.f('ix_patient_identifiers_patient_id'), 'patient_identifiers', ['patient_id'], unique=False)

    op.create_table('patient_merge_log',
    sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
    sa.Column('source_type', sa.String(length=50), nullable=False),
    sa.Column('source_patient_id', sa.UUID(), nullable=False),
    sa.Column('target_patient_id', sa.UUID(), nullable=False),
    sa.Column('requested_by', sa.UUID(), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('approved_by', sa.UUID(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('unmerge_reason', sa.Text(), nullable=True),
    sa.Column('before_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('after_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source_type IN ('thid', 'duplicate_uhid')", name='ck_patient_merge_log_source_type'),
    sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'unmerged')", name='ck_patient_merge_log_status'),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['source_patient_id'], ['patients.id'], ),
    sa.ForeignKeyConstraint(['target_patient_id'], ['patients.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_patient_merge_log_source_patient_id'), 'patient_merge_log', ['source_patient_id'], unique=False)
    op.create_index(op.f('ix_patient_merge_log_target_patient_id'), 'patient_merge_log', ['target_patient_id'], unique=False)
    _create_sequences_for_existing_facilities()


def downgrade() -> None:
    op.drop_index(op.f('ix_patient_merge_log_target_patient_id'), table_name='patient_merge_log')
    op.drop_index(op.f('ix_patient_merge_log_source_patient_id'), table_name='patient_merge_log')
    op.drop_table('patient_merge_log')
    op.drop_index(op.f('ix_patient_identifiers_patient_id'), table_name='patient_identifiers')
    op.drop_index(op.f('ix_patient_identifiers_identifier_blind_index'), table_name='patient_identifiers')
    op.drop_table('patient_identifiers')
    op.drop_index('ix_patients_full_name_trgm', table_name='patients')
    op.drop_index('uq_patients_thid', table_name='patients')
    op.drop_index('uq_patients_uhid', table_name='patients')
    op.drop_table('patients')


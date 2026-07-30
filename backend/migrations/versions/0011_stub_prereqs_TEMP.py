from alembic import op

revision = "0011"
down_revision = "0003_stub_TEMP"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name TEXT NOT NULL,
            code VARCHAR(20) UNIQUE NOT NULL,
            facility_id UUID NOT NULL REFERENCES facilities(id),
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            patient_id UUID NOT NULL,
            facility_id UUID REFERENCES facilities(id),
            department_id UUID REFERENCES departments(id),
            status VARCHAR(30) NOT NULL DEFAULT 'registered',
            visit_date TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS prescriptions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            encounter_id UUID,
            patient_id UUID NOT NULL,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS prescription_items (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            prescription_id UUID NOT NULL REFERENCES prescriptions(id) ON DELETE CASCADE,
            medicine_item_id UUID,
            medicine_name TEXT NOT NULL,
            dosage VARCHAR(50),
            frequency VARCHAR(50),
            duration_days INT,
            route VARCHAR(30),
            instructions TEXT,
            status VARCHAR(30) NOT NULL DEFAULT 'prescribed',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prescription_items")
    op.execute("DROP TABLE IF EXISTS prescriptions")
    op.execute("DROP TABLE IF EXISTS visits")
    op.execute("DROP TABLE IF EXISTS departments")

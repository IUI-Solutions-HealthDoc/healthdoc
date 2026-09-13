"""Maximum facility codes must survive numbering and migration without truncation."""

import importlib
from datetime import date

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import DBAPIError

from app.billing import models, service
from tests.billing.conftest import seed_facility


@pytest.mark.parametrize("model,column,kind,prefix", [
    (models.Invoice, "invoice_number", "invoice", "INV"),
    (models.Payment, "receipt_number", "receipt", "RCP"),
    (models.Refund, "refund_number", "refund", "RFD"),
])
async def test_all_number_allocators_fit_the_real_columns(db, model, column, kind, prefix):
    code = "TESTFACILITY12345678"
    assert len(code) == 20
    facility = await seed_facility(db, code=code)
    number = await service._allocate_billing_number(
        db, facility, kind, prefix, business_date=date(2026, 9, 13),
    )
    assert number == f"{prefix}-{code}-20260913-00001"
    width = await db.scalar(sa.text(
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :table AND column_name = :column"
    ), {"table": model.__tablename__, "column": column})
    assert len(number) <= width == model.__table__.c[column].type.length == 50


async def test_width_migration_preserves_numbers_and_refuses_destructive_downgrade(db, monkeypatch):
    migration = importlib.import_module("migrations.versions.0072_billing_identifier_width")
    for table, column in migration.FIELDS:
        await db.execute(sa.text(
            f"CREATE TEMP TABLE {table} ({column} varchar(30) NOT NULL UNIQUE) ON COMMIT DROP"
        ))
        await db.execute(sa.text(f"INSERT INTO {table} VALUES ('original-number')"))
    connection = await db.connection()

    def run(sync_connection, operation):
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(sync_connection)))
        operation()

    await connection.run_sync(run, migration.upgrade)
    await connection.run_sync(run, migration.downgrade)
    await connection.run_sync(run, migration.upgrade)
    long_number = "RFD-TESTFACILITY12345678-20260913-00001"
    await db.execute(sa.text("INSERT INTO refunds VALUES (:number)"), {"number": long_number})
    with pytest.raises(DBAPIError, match="Long billing identifiers exist"):
        async with connection.begin_nested():
            await connection.run_sync(run, migration.downgrade)
    # Database collation differs between macOS development and Linux CI. This
    # proves exact preservation (including row count), not locale-specific sort.
    numbers = (await db.execute(sa.text("SELECT refund_number FROM refunds"))).scalars().all()
    assert sorted(numbers) == sorted([long_number, "original-number"])

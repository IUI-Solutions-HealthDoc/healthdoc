
import os
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set",
)


@pytest.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _seed_minimal_batch(db_session) -> tuple[str, str, str]:
    """Returns (batch_id, item_id, user_id).

    user_id is a REAL users row, not a bare uuid4(). stock_ledger.performed_by
    is an FK to users.id, so a generated UUID fails with
    fk_stock_ledger_performed_by — which is the constraint doing its job:
    a stock movement has to be attributable to somebody who exists.
    """
    facility_id = str(uuid.uuid4())
    item_id = str(uuid.uuid4())
    location_id = str(uuid.uuid4())
    batch_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    await db_session.execute(text(
        "INSERT INTO facilities (id, code, name, state_code) "
        "VALUES (:id, 'TESTFAC', 'Test Facility', 'TS')"
    ), {"id": facility_id})
    await db_session.execute(text(
        "INSERT INTO inventory_items (id, name, item_type) "
        "VALUES (:id, 'Test Medicine', 'medicine')"
    ), {"id": item_id})
    await db_session.execute(text(
        "INSERT INTO stock_locations (id, name, facility_id) "
        "VALUES (:id, 'Test Pharmacy', :facility_id)"
    ), {"id": location_id, "facility_id": facility_id})
    await db_session.execute(text(
        "INSERT INTO inventory_batches (id, item_id, batch_number, expiry_date, "
        "quantity, stock_location_id) "
        "VALUES (:id, :item_id, 'TESTBATCH', CURRENT_DATE + INTERVAL '1 year', "
        "100, :location_id)"
    ), {"id": batch_id, "item_id": item_id, "location_id": location_id})
    await db_session.execute(text(
        "INSERT INTO users (id, keycloak_sub, username, full_name, facility_id) "
        "VALUES (:id, :sub, :username, 'Stock Test User', :facility_id)"
    ), {"id": user_id, "sub": f"sub-{user_id}", "username": f"stocktest-{user_id[:8]}",
        "facility_id": facility_id})

    return batch_id, item_id, user_id


async def test_ledger_insert_actually_updates_batch_quantity_via_trigger(db_session):
    batch_id, item_id, user_id = await _seed_minimal_batch(db_session)

    await db_session.execute(text("""
        INSERT INTO stock_ledger
            (id, item_id, batch_id, transaction_type, quantity, performed_by)
        VALUES (:id, :item_id, :batch_id, 'issue', -15, :performed_by)
    """), {
        "id": str(uuid.uuid4()), "item_id": item_id, "batch_id": batch_id,
        "performed_by": user_id,
    })

    result = await db_session.execute(
        text("SELECT quantity FROM inventory_batches WHERE id = :id"), {"id": batch_id}
    )
    assert result.scalar_one() == Decimal("85")


async def test_direct_quantity_update_is_rejected_by_guard_trigger(db_session):
    batch_id, _, _ = await _seed_minimal_batch(db_session)

    with pytest.raises(Exception) as exc_info:
        await db_session.execute(text(
            "UPDATE inventory_batches SET quantity = 999 WHERE id = :id"
        ), {"id": batch_id})
        await db_session.commit()

    assert "may only change via a stock_ledger insert" in str(exc_info.value)


async def test_row_version_increments_on_ledger_driven_update(db_session):
    batch_id, item_id, user_id = await _seed_minimal_batch(db_session)

    before = (await db_session.execute(
        text("SELECT row_version FROM inventory_batches WHERE id = :id"), {"id": batch_id}
    )).scalar_one()

    await db_session.execute(text("""
        INSERT INTO stock_ledger
            (id, item_id, batch_id, transaction_type, quantity, performed_by)
        VALUES (:id, :item_id, :batch_id, 'issue', -1, :performed_by)
    """), {
        "id": str(uuid.uuid4()), "item_id": item_id, "batch_id": batch_id,
        "performed_by": user_id,
    })

    after = (await db_session.execute(
        text("SELECT row_version FROM inventory_batches WHERE id = :id"), {"id": batch_id}
    )).scalar_one()

    assert after == before + 1

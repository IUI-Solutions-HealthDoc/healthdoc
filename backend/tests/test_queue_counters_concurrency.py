"""tests/test_queue_counters_concurrency.py

Proves queue_counters is race-safe against real Postgres (SQLite has no
row locking, so the main suite can't test this). Auto-skips if the real
DB isn't reachable or queue_counters doesn't exist yet -- starts running
on its own once that changes, nothing to edit.

Tests _allocate_token_number() directly (not the full create_token()
flow) so it only needs a real facility + department, not patients/visits.
"""
import asyncio
import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.common.config import get_settings
from app.departments.models import Department
from app.queue import service
from app.queue.models import QueueCounter
from app.users.models import Facility

pytestmark = pytest.mark.asyncio


async def _real_database_is_ready() -> bool:
    try:
        engine = create_async_engine(get_settings().database_url)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT to_regclass('public.queue_counters')"))
            exists = result.scalar() is not None
        await engine.dispose()
        return exists
    except Exception:
        return False


async def test_concurrent_token_allocation_never_collides():
    if not await _real_database_is_ready():
        pytest.skip("Real Postgres unreachable or queue_counters missing -- will auto-run once ready.")

    engine = create_async_engine(get_settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    # Real, committed rows -- both concurrent sessions below need to see them.
    #
    # Committed in TWO transactions, parent before child, deliberately. These
    # used to share one flush and relied on SQLAlchemy ordering the facilities
    # INSERT ahead of the departments one; on real Postgres that produced
    # "Key (facility_id)=(...) is not present in table facilities". This test
    # only started running once 0009 unparked and queue_counters existed, so
    # the ordering had never actually been exercised. Two commits is also
    # closer to what the comment above promises: a row a *separate* session
    # can see has to be committed, not merely flushed.
    facility_id = uuid.uuid4()
    department_id = uuid.uuid4()
    async with Session() as setup:
        setup.add(Facility(id=facility_id, code=f"CONC{uuid.uuid4().hex[:4]}", name="Concurrency Test", state_code="TS"))
        await setup.commit()
    async with Session() as setup:
        setup.add(Department(id=department_id, code=f"C{uuid.uuid4().hex[:4]}", name="Concurrency Test", facility_id=facility_id))
        await setup.commit()

    business_date = date.today()

    async def allocate_in_own_session() -> int:
        # Own connection/transaction each -- a single shared session can't contend with itself.
        async with Session() as session:
            async with session.begin():
                return await service._allocate_token_number(session, department_id, business_date)

    try:
        results = await asyncio.gather(allocate_in_own_session(), allocate_in_own_session())

        assert results[0] != results[1]
        assert sorted(results) == [1, 2]

        async with Session() as check:
            row = (
                await check.execute(
                    QueueCounter.__table__.select().where(
                        QueueCounter.department_id == department_id,
                        QueueCounter.counter_date == business_date,
                    )
                )
            ).first()
            assert row.last_value == 2
    finally:
        # Real rows were committed, so clean up even if an assertion above failed.
        async with Session() as cleanup:
            await cleanup.execute(QueueCounter.__table__.delete().where(QueueCounter.department_id == department_id))
            await cleanup.execute(Department.__table__.delete().where(Department.id == department_id))
            await cleanup.execute(Facility.__table__.delete().where(Facility.id == facility_id))
            await cleanup.commit()

    await engine.dispose()
    

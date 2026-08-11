"""Seed a real facility -> user -> patient -> visit -> encounter -> order chain
for the pathology and radiology API tests.

Why this is needed now: the handlers do

    from app.orders.models import Order
    order = await db.get(Order, order_id)
    if order is None: raise HTTPException(404)

app/orders/models.py used to import app.common.database and app.common.mixins,
neither of which exists, so that import always raised and `Order` was set to
None — the lookup was skipped entirely and any random UUID passed. With the
import fixed, the check runs, and a random order_id correctly 404s.

So the tests need a real order. Everything above it in the FK chain has to
exist too, which is why this seeds six tables.

Sync wrapper around async inserts: these are TestClient tests, so the test
functions themselves are synchronous and can't await a fixture. asyncio.run()
on its own short-lived engine keeps it off the app's connection pool.

Rows are committed and deliberately not torn down — the ids are fixed, the
inserts are idempotent via ON CONFLICT DO NOTHING, and later runs reuse them.
Same accumulate-rather-than-delete discipline as tests/audit/conftest.py:
anything pointing at these rows would block a DELETE anyway.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://healthdoc:change-me@localhost:5432/healthdoc_test",
)

# Fixed ids so repeated runs reuse the same rows instead of accumulating.
FACILITY_ID = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
PATIENT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
VISIT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
ENCOUNTER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
ORDER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d1")


def _user_id_for(sub: str) -> uuid.UUID:
    """Must match tests/*/conftest.py's _db_user_for — created_by is an FK to
    users.id, so the row the token resolves to has to actually exist."""
    return uuid.uuid5(uuid.NAMESPACE_OID, sub)


async def _seed(subs: list[str]) -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text(
                "INSERT INTO facilities (id, code, name, state_code) "
                "VALUES (:id, 'LABTST', 'Lab Test Facility', 'TS') "
                "ON CONFLICT (id) DO NOTHING"), {"id": FACILITY_ID})

            for sub in subs:
                await conn.execute(sa.text(
                    "INSERT INTO users (id, keycloak_sub, username, full_name, facility_id) "
                    "VALUES (:id, :sub, :username, 'Lab Test User', :facility_id) "
                    "ON CONFLICT (id) DO NOTHING"),
                    {"id": _user_id_for(sub), "sub": sub,
                     "username": f"labtest-{str(_user_id_for(sub))[:8]}",
                     "facility_id": FACILITY_ID})

            creator = _user_id_for(subs[0])
            await conn.execute(sa.text(
                "INSERT INTO patients (id, full_name, sex, identity_path, facility_id, "
                " created_by, age_years, uhid) "
                "VALUES (:id, 'Lab Test Patient', 'other', 'demographics_only', :fac, "
                "        :by, 30, 'IN-TS-LABTST-2026-000001') "
                "ON CONFLICT (id) DO NOTHING"),
                {"id": PATIENT_ID, "fac": FACILITY_ID, "by": creator})

            await conn.execute(sa.text(
                "INSERT INTO visits (id, visit_number, patient_id, facility_id, visit_type, "
                " visit_date, created_by) "
                "VALUES (:id, 'V-LABTEST-0001', :pid, :fac, 'opd', CURRENT_DATE, :by) "
                "ON CONFLICT (id) DO NOTHING"),
                {"id": VISIT_ID, "pid": PATIENT_ID, "fac": FACILITY_ID, "by": creator})

            await conn.execute(sa.text(
                "INSERT INTO encounters (id, visit_id, provider_user_id, created_by) "
                "VALUES (:id, :vid, :prov, :by) ON CONFLICT (id) DO NOTHING"),
                {"id": ENCOUNTER_ID, "vid": VISIT_ID, "prov": creator, "by": creator})

            await conn.execute(sa.text(
                "INSERT INTO orders (id, order_number, encounter_id, patient_id, order_type, "
                " created_by) "
                "VALUES (:id, 'ORD-LABTEST-0001', :eid, :pid, 'lab', :by) "
                "ON CONFLICT (id) DO NOTHING"),
                {"id": ORDER_ID, "eid": ENCOUNTER_ID, "pid": PATIENT_ID, "by": creator})
    finally:
        await engine.dispose()


def seed_order_chain(subs: list[str]) -> str:
    """Returns a real orders.id the handlers will find. Safe to call repeatedly."""
    asyncio.run(_seed(subs))
    return str(ORDER_ID)

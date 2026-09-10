"""Tariff HTTP replay and observed contention on the migrated PostgreSQL schema.

Only a named test database is accepted. Each test owns a unique synthetic
facility; committed fixtures remain there, never in the application database.
"""
import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.deps import AuthUser, DbUser, get_current_user
from app.billing import router as routes
from app.billing import service
from app.billing.schemas import TariffCreate
from app.billing.tariff_safety import reserve_tariff_write
from app.common.db import get_db
from app.common.envelope import EnvelopeMiddleware
from tests.billing.conftest import seed_facility, seed_user

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pg_tariffs(engine):
    url = make_url(os.environ["TEST_DATABASE_URL"])
    assert url.get_backend_name() == "postgresql"
    assert url.database and (url.database.endswith("_test") or url.database.startswith("test_"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        facility = await seed_facility(db)
        foreign = await seed_facility(db)
        subjects = [str(uuid.uuid4()) for _ in range(3)]
        actors = [await seed_user(db, facility_id=target, keycloak_sub=sub)
                  for target, sub in zip([facility, facility, foreign], subjects, strict=True)]
        await db.commit()

    @asynccontextmanager
    async def client(index=0, roles=None):
        app = FastAPI()
        app.add_middleware(EnvelopeMiddleware)
        app.include_router(routes.router, prefix="/api/v1")

        async def database():
            async with sessions() as db:
                try:
                    yield db
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise

        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: AuthUser(
            sub=subjects[index], roles=roles or ["billing"])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
            yield http

    return SimpleNamespace(sessions=sessions, client=client, facility=facility, foreign=foreign,
                           actors=actors, subjects=subjects)


def payload(**overrides):
    return {"charge_code": "TEST-CBC", "description": "Synthetic tariff", "charge_category": "lab",
            "unit_price": "71.23", "scheme_code": None, "effective_from": "2030-01-10", **overrides}


async def create(http, body=None, key=None):
    return await http.post("/api/v1/billing/charge-master", json=body or payload(),
                           headers={"Idempotency-Key": key} if key is not None else {})


async def catalogue(pg):
    async with pg.sessions() as db:
        return await service.list_charge_master(db, pg.facility, active_only=False)


async def test_tariff_creation_requires_an_action_key(pg_tariffs):
    async with pg_tariffs.client() as http:
        result = await create(http)
        assert result.status_code == 400
    assert await catalogue(pg_tariffs) == []


async def test_tariff_create_replays_exact_committed_response(pg_tariffs):
    key = str(uuid.uuid4())
    async with pg_tariffs.client() as http:
        first = await create(http, key=key)
        assert first.status_code == 201
        replay = await create(http, key=key)
        assert replay.status_code == 201
        assert replay.json()["data"] == first.json()["data"]
    assert len(await catalogue(pg_tariffs)) == 1


async def test_tariff_retirement_replays_success_without_retiring_again(pg_tariffs):
    async with pg_tariffs.client() as http:
        made = await create(http, key=str(uuid.uuid4()))
        ident = made.json()["data"]["id"]
        path = f"/api/v1/billing/charge-master/{ident}/deactivate"
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        first = await http.post(path, headers=headers)
        replay = await http.post(path, headers=headers)
        assert first.status_code == replay.status_code == 204
        assert first.content == replay.content == b""
    row, = await catalogue(pg_tariffs)
    assert not row.is_active and row.unit_price == Decimal("71.23")


async def run_contended(pg, first_operation, second_operation):
    """Hold an actual transaction open and prove the contender waits in PG."""
    first_inside, release_first, second_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    contender_pid = None

    async def first():
        async with pg.sessions() as db:
            result = await first_operation(db)
            first_inside.set()
            await asyncio.wait_for(release_first.wait(), 10)
            await db.commit()
            return result

    async def second():
        nonlocal contender_pid
        async with pg.sessions() as db:
            contender_pid = await db.scalar(sa.text("SELECT pg_backend_pid()"))
            second_started.set()
            try:
                result = await second_operation(db)
                await db.commit()
                return result
            except service.TariffOverlap:
                await db.rollback()
                return "overlap"

    leader, contender = asyncio.create_task(first()), None
    try:
        await asyncio.wait_for(first_inside.wait(), 10)
        contender = asyncio.create_task(second())
        await asyncio.wait_for(second_started.wait(), 10)

        async def observe_wait():
            async with pg.sessions() as observer:
                while not await observer.scalar(sa.text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND NOT granted)"),
                    {"pid": contender_pid}):
                    if contender.done():
                        raise AssertionError("Tariff contender bypassed serialization")
                    await asyncio.sleep(0.02)

        await asyncio.wait_for(observe_wait(), 10)
        release_first.set()
        return await asyncio.wait_for(asyncio.gather(leader, contender), 10)
    finally:
        release_first.set()
        tasks = [task for task in [leader, contender] if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def insert(pg, db, start=date(2030, 1, 10), scheme=None, actor=None):
    return await service.create_tariff(db, facility_id=pg.facility, charge_code="TEST-CBC",
        description="Synthetic contention", charge_category="lab", unit_price=Decimal("71.23"),
        effective_from=start, scheme_code=scheme, created_by=actor or pg.actors[0])


async def test_concurrent_first_general_tariff_has_one_version_not_two(pg_tariffs):
    first, second = await run_contended(pg_tariffs,
        lambda db: insert(pg_tariffs, db), lambda db: insert(pg_tariffs, db, actor=pg_tariffs.actors[1]))
    assert first != "overlap" and second == "overlap"
    assert len(await catalogue(pg_tariffs)) == 1


async def test_retire_requires_a_key_and_new_key_after_retirement_is_not_replay(pg_tariffs):
    async with pg_tariffs.client() as http:
        made = await create(http, key=str(uuid.uuid4()))
        path = f"/api/v1/billing/charge-master/{made.json()['data']['id']}/deactivate"
        assert (await http.post(path)).status_code == 400
        assert (await catalogue(pg_tariffs))[0].is_active
        assert (await http.post(path, headers={"Idempotency-Key": "first"})).status_code == 204
        assert (await http.post(path, headers={"Idempotency-Key": "another"})).status_code == 404


@pytest.mark.parametrize("key,status", [(" ", 400), ("x" * 256, 422)])
async def test_invalid_action_key_is_refused_before_any_write(pg_tariffs, key, status):
    async with pg_tariffs.client() as http:
        assert (await create(http, key=key)).status_code == status
    assert await catalogue(pg_tariffs) == []


async def test_same_key_different_body_or_retirement_target_is_a_conflict(pg_tariffs):
    async with pg_tariffs.client() as http:
        first = await create(http, key="create")
        assert (await create(http, payload(charge_code="OTHER"), key="create")).status_code == 409
        second = await create(http, payload(charge_code="OTHER"), key="second")
        first_path = f"/api/v1/billing/charge-master/{first.json()['data']['id']}/deactivate"
        other_path = f"/api/v1/billing/charge-master/{second.json()['data']['id']}/deactivate"
        assert (await http.post(first_path, headers={"Idempotency-Key": "retire"})).status_code == 204
        assert (await http.post(other_path, headers={"Idempotency-Key": "retire"})).status_code == 409
    rows = await catalogue(pg_tariffs)
    assert len(rows) == 2 and sum(row.is_active for row in rows) == 1


async def test_same_key_is_actor_scoped_and_cross_facility_retirement_is_404(pg_tariffs):
    async with pg_tariffs.client() as first, pg_tariffs.client(1, ["admin"]) as other:
        a = await create(first, key="shared")
        b = await create(other, payload(charge_code="OTHER"), key="shared")
        assert a.status_code == b.status_code == 201
        assert a.json()["data"]["id"] != b.json()["data"]["id"]
    async with pg_tariffs.client(2) as foreign:
        path = f"/api/v1/billing/charge-master/{a.json()['data']['id']}/deactivate"
        assert (await foreign.post(path, headers={"Idempotency-Key": "shared"})).status_code == 404
    assert all(row.is_active for row in await catalogue(pg_tariffs))


async def test_moving_actor_to_another_facility_cannot_replay_old_response(pg_tariffs):
    async with pg_tariffs.client() as http:
        made = await create(http, key="move")
        async with pg_tariffs.sessions() as db:
            await db.execute(sa.text("UPDATE users SET facility_id=:facility WHERE id=:actor"),
                             {"facility": pg_tariffs.foreign, "actor": pg_tariffs.actors[0]})
            await db.commit()
        replay = await create(http, key="move")
        assert replay.status_code == 409 and replay.json()["data"] is None
        path = f"/api/v1/billing/charge-master/{made.json()['data']['id']}/deactivate"
        assert (await http.post(path, headers={"Idempotency-Key": "retire"})).status_code == 404


@pytest.mark.parametrize("role", ["receptionist", "doctor", "nurse", "pharmacist", "auditor", "superadmin"])
async def test_non_writers_cannot_create_or_retire_even_with_an_action_key(pg_tariffs, role):
    async with pg_tariffs.client() as allowed:
        made = await create(allowed, key="seed")
    async with pg_tariffs.client(1, [role]) as denied:
        assert (await create(denied, key="create")).status_code == 403
        path = f"/api/v1/billing/charge-master/{made.json()['data']['id']}/deactivate"
        assert (await denied.post(path, headers={"Idempotency-Key": "retire"})).status_code == 403
    assert (await catalogue(pg_tariffs))[0].is_active


@pytest.mark.parametrize("operation", ["revision", "retirement"])
async def test_failed_response_record_rolls_back_write_and_reservation(pg_tariffs, monkeypatch, operation):
    async with pg_tariffs.client() as http:
        made = await create(http, key="seed")
        record = routes.record_idempotent_response

        async def fail_record(*args, **kwargs):
            raise RuntimeError("Synthetic response-record failure")

        monkeypatch.setattr(routes, "record_idempotent_response", fail_record)

        async def attempt():
            if operation == "revision":
                return await create(http, payload(effective_from="2030-01-12"), key="retry")
            return await http.post(f"/api/v1/billing/charge-master/{made.json()['data']['id']}/deactivate",
                                   headers={"Idempotency-Key": "retry"})

        with pytest.raises(RuntimeError, match="Synthetic"):
            await attempt()
        row, = await catalogue(pg_tariffs)
        assert row.is_active and row.effective_to is None
        async with pg_tariffs.sessions() as db:
            count = await db.scalar(sa.text("SELECT count(*) FROM idempotency_keys WHERE user_id=:actor AND key='retry'"),
                                    {"actor": pg_tariffs.actors[0]})
            assert count == 0
        monkeypatch.setattr(routes, "record_idempotent_response", record)
        assert (await attempt()).status_code == (201 if operation == "revision" else 204)


async def test_incomplete_reservation_does_not_run_the_mutation(pg_tariffs):
    async with pg_tariffs.sessions() as db:
        await reserve_tariff_write(db, key="incomplete", endpoint="POST /billing/charge-master",
            actor_id=pg_tariffs.actors[0], facility_id=pg_tariffs.facility,
            body=TariffCreate(**payload()).model_dump(mode="json"))
        await db.commit()
    async with pg_tariffs.client() as http:
        result = await create(http, key="incomplete")
        assert result.status_code == 409
        assert result.json()["error"]["message"]["code"] == "idempotency_key_in_progress"
    assert await catalogue(pg_tariffs) == []


async def test_retired_general_version_date_cannot_be_reused(pg_tariffs):
    async with pg_tariffs.client() as http:
        made = await create(http, key="original")
        assert (await http.post(f"/api/v1/billing/charge-master/{made.json()['data']['id']}/deactivate",
                               headers={"Idempotency-Key": "retire"})).status_code == 204
        assert (await create(http, key="duplicate-date")).status_code == 409
        assert (await create(http, payload(effective_from="2030-01-11"), key="new-date")).status_code == 201
    assert len(await catalogue(pg_tariffs)) == 2


async def test_concurrent_next_day_revisions_form_nonoverlapping_history(pg_tariffs):
    first, second = await run_contended(pg_tariffs, lambda db: insert(pg_tariffs, db),
        lambda db: insert(pg_tariffs, db, date(2030, 1, 11), actor=pg_tariffs.actors[1]))
    assert first != second and second != "overlap"
    rows = await catalogue(pg_tariffs)
    old = next(row for row in rows if row.id == first)
    assert old.effective_from == old.effective_to == date(2030, 1, 10)
    assert sum(row.effective_to is None for row in rows) == 1


async def test_concurrent_same_request_replays_after_real_commit(pg_tariffs):
    user = DbUser(id=pg_tariffs.actors[0], facility_id=pg_tariffs.facility,
                  keycloak_sub=pg_tariffs.subjects[0], username="synthetic", roles=["billing"])

    async def request(db):
        result = await routes.create_tariff(TariffCreate(**payload()), current_db_user=user,
            idempotency_key="simultaneous", db=db, user=AuthUser(sub=user.keycloak_sub, roles=user.roles))
        return result.model_dump(mode="json")

    first, replay = await run_contended(pg_tariffs, request, request)
    assert first == replay and len(await catalogue(pg_tariffs)) == 1


async def test_revision_and_retirement_share_the_family_lock(pg_tariffs):
    async with pg_tariffs.sessions() as db:
        ident = await insert(pg_tariffs, db)
        await db.commit()

    async def retire(db):
        return await service.deactivate_tariff(db, ident, updated_by=pg_tariffs.actors[0], facility_id=pg_tariffs.facility)

    retired, revised = await run_contended(pg_tariffs, retire,
        lambda db: insert(pg_tariffs, db, date(2030, 1, 12), actor=pg_tariffs.actors[1]))
    assert retired is True and revised != "overlap"
    rows = await catalogue(pg_tariffs)
    assert not next(row for row in rows if row.id == ident).is_active
    assert next(row for row in rows if row.id == revised).is_active


@pytest.mark.parametrize("override", [
    {"charge_code": " "}, {"description": " "}, {"charge_code": "x" * 31},
    {"unit_price": "10000000000.00"}, {"unit_price": "0.001"}, {"unit_price": "-1"},
    {"effective_from": "2030-02-30"}, {"scheme_code": "x" * 31},
])
async def test_invalid_tariff_payload_is_422_not_a_database_failure(pg_tariffs, override):
    async with pg_tariffs.client() as http:
        assert (await create(http, payload(**override), key="invalid")).status_code == 422
    assert await catalogue(pg_tariffs) == []

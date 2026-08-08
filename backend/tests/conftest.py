import uuid
from datetime import date
from itertools import count

import pytest
from fastapi.testclient import TestClient
import pytest_asyncio
from sqlalchemy.dialects.postgresql import UUID,JSONB, INET
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.main import app
from app.common.db import Base
from app.audit.models import AuditLog
from app.departments.models import Department, Room
from app.users.models import Facility, User
from app.queue import service
from sqlalchemy import ARRAY, Column, Table, event

_test_chain_seq_counter = count(1)
 
 
@event.listens_for(AuditLog, "before_insert")
def _assign_test_chain_seq(mapper, connection, target):
    if target.chain_seq is None:
        target.chain_seq = next(_test_chain_seq_counter)

@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Replace Redis publish_event with a no-op during tests."""
    async def fake_publish(channel, event_type, payload):
        # You can collect calls here if you want to assert later
        return True

    # Patch the publish_event function used in your queue service
    monkeypatch.setattr("app.queue.service.publish_event", fake_publish, raising=False)
    monkeypatch.setattr("app.queue.router.publish_event", fake_publish, raising=False)

@pytest.fixture(autouse=True)
def fake_business_date(monkeypatch):
    async def fake_get_business_date(db, facility_id):
        return date.today()
 
    monkeypatch.setattr("app.queue.service.get_business_date", fake_get_business_date)


def _ensure_stub_tables_exist() -> None:
    referenced_tables: set[str] = set()
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            referenced_tables.add(fk.target_fullname.split(".")[0])
 
    missing = referenced_tables - set(Base.metadata.tables.keys())
    for table_name in missing:
        Table(
            table_name, Base.metadata,
            Column("id", UUID(as_uuid=True), primary_key=True),
            extend_existing=True,
        )
        
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(INET, "sqlite")
def _compile_inet_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):
    """`Base.metadata.create_all` here materialises EVERY model in the app, not
    just the queue module's — so a Postgres-only type anywhere in the project
    breaks these tests. `consent_records.scope` (ARRAY(Text), migration 0004)
    did exactly that the moment 0004 merged.

    TEXT is only good enough to make the DDL render; nothing here reads or
    writes that column. If a test ever needs real array semantics it belongs on
    Postgres, like tests/consent and tests/audit already are.
    """
    return "TEXT"
 
@pytest_asyncio.fixture
async def db():
    """A fresh, empty, in-memory database — created and destroyed once per
    test. Has no connection to your real Postgres DB."""

    _ensure_stub_tables_exist()

    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    @event.listens_for(engine.sync_engine, "connect")
    def _register_pg_functions(dbapi_connection, connection_record):
        dbapi_connection.create_function("uuid_generate_v4", 0, lambda: str(uuid.uuid4()))
        # break_glass_grants (0004) has CHECK (char_length(justification) >= 20).
        # SQLite spells it length(). Same reason as the type shims above: this
        # conftest creates every table in the app, so one module's Postgres-ism
        # breaks another module's tests.
        dbapi_connection.create_function("char_length", 1, lambda s: len(s) if s else 0)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
 
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
 
    await engine.dispose()
 
 
@pytest_asyncio.fixture
async def seed(db):
    """One facility, one department, one room, one doctor user."""
    facility = Facility(id=uuid.uuid4(), code="TST01", name="Test Facility", state_code="TS")
    dept = Department(id=uuid.uuid4(), code="TST", name="Test Dept", facility_id=facility.id)
    room = Room(id=uuid.uuid4(), department_id=dept.id, room_number="1")
    doctor = User(
        id=uuid.uuid4(),
        keycloak_sub=f"test-sub-{uuid.uuid4()}",
        username=f"testdoc{uuid.uuid4().hex[:6]}",
        full_name="Dr. Test",
        facility_id=facility.id,
    )
    db.add_all([facility, dept, room, doctor])
    await db.flush()
    return dept, room, doctor
 
 
@pytest_asyncio.fixture
async def queue(db, seed):
    dept, room, doctor = seed
    q = await service.create_queue(
        db,
        department_id=dept.id,
        doctor_user_id=doctor.id,
        room_id=room.id,
        display_label="Test Queue",
        service_date=date.today(),
        caller_facility_id=dept.facility_id,
    )
    return q
 

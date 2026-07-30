import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
import pytest_asyncio
from sqlalchemy.dialects.postgresql import UUID,JSONB
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.main import app
from app.common.db import Base
from app.departments.models import Department, Room
from app.users.models import Facility, User
from app.queue import service
from sqlalchemy import Column

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
    monkeypatch.setattr("app.queue.service.publish_event", fake_publish)

class Visit(Base):
        __tablename__ = "visits"
        id = Column(UUID(as_uuid=True), primary_key=True)  

@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"
 
 
@pytest_asyncio.fixture
async def db():
    """A fresh, empty, in-memory database — created and destroyed once per
    test. Has no connection to your real Postgres DB."""

    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
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
    )
    return q
 
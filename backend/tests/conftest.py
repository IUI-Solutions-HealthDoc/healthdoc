import uuid
import re
import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.main import app
from app.common.db import Base, get_db
from app.common.config import get_settings
from app.auth.deps import get_current_user, AuthUser
from app.users.models import User, Facility

TEST_DATABASE_URL = re.sub(r"/([^/]+)$", "/healthdoc_test", get_settings().database_url)

engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = TestSessionLocal(bind=conn)
        yield session
        await session.close()
        await trans.rollback()


@pytest_asyncio.fixture
async def fake_facility(db_session):
    facility = Facility(
        code="TST001",
        name="Test Facility",
        state_code="RJ",
    )
    db_session.add(facility)
    await db_session.flush()
    await db_session.refresh(facility)
    return facility


@pytest_asyncio.fixture
async def fake_user_row(db_session, fake_facility):
    """Seeds a real users row matching fake_auth_user.sub, since FKs
    (created_by, handed_over_to, moved_by...) need a real users.id."""
    user = User(
        keycloak_sub="test-keycloak-sub",
        username="test.user",
        full_name="Test User",
        facility_id=fake_facility.id,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest.fixture
def fake_auth_user() -> AuthUser:
    return AuthUser(
        sub="test-keycloak-sub",
        username="test.user",
        roles=["doctor", "nurse", "admin"],
    )


@pytest_asyncio.fixture
async def authed_client(fake_auth_user, fake_user_row, db_session):
    """Auth bypassed + real seeded user row + real (rolled-back) DB session."""
    app.dependency_overrides[get_current_user] = lambda: fake_auth_user
    app.dependency_overrides[get_db] = lambda: db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)

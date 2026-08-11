"""Auth overrides for the radiology API tests (mirror of tests/pathology/conftest.py).

These tests override FastAPI dependencies rather than minting real JWTs, so
every dependency the routers actually declare has to be overridden — not
just the first one.

get_current_user alone is no longer enough. The routers take CurrentDbUser,
which is Annotated[DbUser, Depends(get_current_db_user)], and
get_current_db_user does a real SELECT against `users` keyed on the token's
keycloak_sub. With only get_current_user overridden, that lookup finds
nothing and returns 403 actor_not_provisioned — which is the dependency
doing its job, not a test-harness quirk: a token whose subject has no
provisioned users row genuinely should not be able to write.

So client_as overrides both, and the DbUser it returns carries an `id` and a
`facility_id`, because the handlers use them for created_by and for the
accession allocator's business date.
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.common.db import get_db
from app.main import app
from tests._lab_seed import TEST_DATABASE_URL

# One facility for the whole suite — the accession counter is keyed on
# (prefix, business date), and business date is read from this facility's
# timezone, so a stable id keeps the tests deterministic.
TEST_FACILITY_ID = uuid.UUID("00000000-0000-0000-0000-0000000000f1")

LAB_TECH = AuthUser(sub=str(uuid.uuid4()), username="tech1", roles=["lab_tech"])
DOCTOR = AuthUser(sub=str(uuid.uuid4()), username="doc1", roles=["doctor"])
RADIOLOGIST = AuthUser(sub=str(uuid.uuid4()), username="rad1", roles=["radiologist"])
RADIOLOGY_TECH = AuthUser(sub=str(uuid.uuid4()), username="radtech1", roles=["radiology_tech"])


def _db_user_for(user: AuthUser) -> DbUser:
    """The app-side users row the token would resolve to.

    id is derived from the sub so it's stable across calls within a test —
    created_by/updated_by are FKs to users.id, and a fresh uuid4() per
    request would make those columns meaningless.
    """
    return DbUser(
        id=uuid.uuid5(uuid.NAMESPACE_OID, user.sub),
        keycloak_sub=user.sub,
        username=user.username,
        facility_id=TEST_FACILITY_ID,
        roles=user.roles,
    )


# A NullPool engine for the API tests, and get_db overridden to use it.
#
# app.common.db's engine is created at import time with a QueuePool, and each
# test gets its own TestClient and therefore its own event loop. A pooled
# connection opened in one test's loop then gets handed to the next test,
# whose loop is different — "RuntimeError: Event loop is closed", and enough
# pending-task noise to bury the real assertion.
#
# NullPool opens and closes a connection per checkout, so nothing survives a
# loop boundary. Slower, irrelevant at this scale, and the alternative is
# disposing a global engine from a foreign loop, which is worse.
_test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
_TestSession = async_sessionmaker(_test_engine, expire_on_commit=False)


async def _test_get_db():
    """Mirrors app.common.db.get_db exactly — commit on success, roll back on
    error — so the handlers behave identically to production."""
    async with _TestSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture
def client_as():
    """One TestClient, entered as a context manager, per test.

    The `with` matters more than it looks. Outside a context manager,
    starlette's TestClient spins up a fresh portal — and therefore a fresh
    event loop — for EVERY request. app.common.db's engine is module-level
    with a QueuePool, so connections opened during request 1 get handed back
    out during request 2, whose loop is different: "RuntimeError: Event loop
    is closed", plus enough pending-task noise to bury the real assertion.

    Entering the client once pins a single loop for the whole test, and also
    runs the app's lifespan events, which is closer to production anyway.

    Switching identity is just swapping the dependency override; it needs no
    second client.
    """
    with TestClient(app) as client:
        def _make(user: AuthUser) -> TestClient:
            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_current_db_user] = lambda: _db_user_for(user)
            app.dependency_overrides[get_db] = _test_get_db
            return client

        yield _make

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_db_user, None)
    app.dependency_overrides.pop(get_db, None)

@pytest.fixture(scope="session")
def seeded_order_id() -> str:
    """A real orders.id, with its whole FK chain committed.

    The handlers look the order up and 404 when it's absent — that check was
    dead code until app/orders/models.py became importable, which is why the
    tests could previously pass a random UUID.
    """
    from tests._lab_seed import seed_order_chain
    return seed_order_chain([u.sub for u in (DOCTOR, LAB_TECH, RADIOLOGIST, RADIOLOGY_TECH)])

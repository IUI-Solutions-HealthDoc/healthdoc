"""Auth overrides for the pathology and radiology API tests.

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

from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.main import app

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


@pytest.fixture
def client_as():
    """One TestClient per test, re-pointed at different users as needed.

    Deliberately NOT a new TestClient per role. Each TestClient runs the app
    on its own event loop, while app.common.db's engine is module-level and
    its pool outlives them — so a test that did client_as(DOCTOR) then
    client_as(LAB_TECH) handed the second loop connections created in the
    first, which is "RuntimeError: Event loop is closed" and a pile of
    pending-task noise that buries the real assertion.

    Switching identity is just swapping the dependency override; it needs no
    new client.
    """
    client = TestClient(app)

    def _make(user: AuthUser) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_current_db_user] = lambda: _db_user_for(user)
        return client

    yield _make

    client.close()
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_db_user, None)

@pytest.fixture(scope="session")
def seeded_order_id() -> str:
    """A real orders.id, with its whole FK chain committed.

    The handlers look the order up and 404 when it's absent — that check was
    dead code until app/orders/models.py became importable, which is why the
    tests could previously pass a random UUID.
    """
    from tests._lab_seed import seed_order_chain
    return seed_order_chain([u.sub for u in (DOCTOR, LAB_TECH, RADIOLOGIST, RADIOLOGY_TECH)])

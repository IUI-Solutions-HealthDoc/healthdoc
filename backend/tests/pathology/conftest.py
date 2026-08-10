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
    """TestClient with both auth dependencies overridden for the given user."""
    def _make(user: AuthUser) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_current_db_user] = lambda: _db_user_for(user)
        return TestClient(app)

    yield _make

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_db_user, None)

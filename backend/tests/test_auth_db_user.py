"""get_current_db_user — the three outcomes, exercised rather than asserted about.

These use a hand-built fake session instead of a live database on purpose: the
behaviour under test is entirely in the dependency (which row shape maps to which
outcome), not in Postgres. A DB-backed test here would prove the same three things
more slowly.

What is NOT covered here, deliberately: that `keycloak_sub` is UNIQUE and indexed.
That's the migration's job and 0002 already has it.
"""
import uuid

import pytest
from fastapi import HTTPException

from app.auth.deps import AuthUser, get_current_db_user


class _Row:
    def __init__(self, *, is_active=True, facility_id=None):
        self.id = uuid.uuid4()
        self.keycloak_sub = "kc-sub-123"
        self.username = "r.kumar"
        self.facility_id = facility_id or uuid.uuid4()
        self.is_active = is_active


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    """Minimal stand-in for AsyncSession — only `execute(...).first()` is used."""

    def __init__(self, row):
        self._row = row

    async def execute(self, _stmt):
        return _Result(self._row)


def _jwt_user() -> AuthUser:
    return AuthUser(sub="kc-sub-123", username="r.kumar", roles=["doctor", "admin"])


@pytest.mark.asyncio
async def test_returns_users_id_not_the_keycloak_sub():
    """The whole reason this dependency exists.

    Three defects came from writing `sub` into a column that foreign-keys to
    users.id, so the one thing this must guarantee is that `.id` and `.sub` are
    different values and `.id` is the database one.
    """
    row = _Row()
    user = await get_current_db_user(_jwt_user(), _FakeSession(row))

    assert user.id == row.id
    assert str(user.id) != user.keycloak_sub
    assert user.keycloak_sub == "kc-sub-123"


@pytest.mark.asyncio
async def test_facility_id_comes_from_the_database_row():
    """Facility scoping reads this, so it must come from the user's row and not
    from anything the caller can influence."""
    row = _Row()
    user = await get_current_db_user(_jwt_user(), _FakeSession(row))
    assert user.facility_id == row.facility_id


@pytest.mark.asyncio
async def test_roles_come_from_the_token_not_the_row():
    """Keycloak owns roles; `users` has no role column. The row in this fake
    carries none, and the result must still show the token's."""
    user = await get_current_db_user(_jwt_user(), _FakeSession(_Row()))
    assert user.roles == ["doctor", "admin"]


@pytest.mark.asyncio
async def test_no_profile_is_403_actor_not_provisioned():
    """A valid token whose subject has no users row can't be attributed, so the
    mutation must not proceed."""
    with pytest.raises(HTTPException) as exc:
        await get_current_db_user(_jwt_user(), _FakeSession(None))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "actor_not_provisioned"


@pytest.mark.asyncio
async def test_deactivated_user_is_403_and_distinguishable():
    """Distinct from the above: the profile exists and was switched off. An admin
    reading the log needs to tell 'never set up' from 'turned off' — the fixes
    differ."""
    with pytest.raises(HTTPException) as exc:
        await get_current_db_user(_jwt_user(), _FakeSession(_Row(is_active=False)))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "user_deactivated"

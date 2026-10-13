"""The control-room server's database role is enough, and no more.

infra/control-room/db-role.sql is what the separate control-room host connects
as. A grant missing there shows up in production as a board that never loads,
so every control-room test in test_control_room.py is rerun here with the
officer endpoints executing as that role. Seeding and the 15-minute capture
still run as the owner: both happen on the hospital server.

The other half is the point of a separate server: the role must not be able to
read patients or change clinical data.
"""

import inspect
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from app.audit import session_router
from app.monitor import router as monitor_router
from app.monitor import service
from tests.monitor import test_control_room as suite

pytestmark = pytest.mark.asyncio

ROLE = "healthdoc_control_room"
ROLE_SQL = Path(__file__).resolve().parents[3] / "infra" / "control-room" / "db-role.sql"

# Only the cases that take nothing but a session: the others patch Keycloak for
# the superadmin's officer management, which runs on the hospital server.
CASES = sorted(
    name for name, fn in vars(suite).items()
    if name.startswith("test_") and list(inspect.signature(fn).parameters) == ["db"]
)

# What the control-room host runs: its routes, nothing that writes snapshots.
AS_CONTROL_ROOM = [
    (monitor_router, "get_board"),
    (monitor_router, "get_facility_detail"),
    (monitor_router, "get_disease_trends"),
    (monitor_router, "get_facility_activity"),
    (session_router, "record_login"),
]


async def _create_role(db) -> None:
    # The file is several statements and a DO block: run it through asyncpg's
    # simple protocol, inside the test's transaction so it rolls back.
    raw = await (await db.connection()).get_raw_connection()
    await raw.driver_connection.execute(ROLE_SQL.read_text())


def _as_role(db, original):
    async def wrapped(*args, **kwargs):
        await db.execute(sa.text(f"SET ROLE {ROLE}"))
        result = await original(*args, **kwargs)
        await db.flush()  # audit rows and snapshots are written as the role too
        await db.execute(sa.text("RESET ROLE"))
        return result
    return wrapped


@pytest.mark.parametrize("case", CASES)
async def test_the_control_room_runs_as_its_own_role(db, monkeypatch, case):
    await _create_role(db)
    monkeypatch.setattr(service, "utcnow", lambda: suite.NOW)
    for module, name in AS_CONTROL_ROOM:
        monkeypatch.setattr(module, name, _as_role(db, getattr(module, name)))
    await getattr(suite, case)(db)


async def test_every_control_room_case_is_covered():
    # A rename that drops the capture case would leave this file checking nothing.
    assert "test_capture_counts_from_the_source_tables" in CASES
    assert "test_the_trail_shows_who_did_what_with_patients_masked_and_audited" in CASES
    assert len(CASES) >= 15


@pytest.mark.parametrize("statement", [
    "SELECT full_name FROM patients LIMIT 1",
    "SELECT abha_number FROM patients LIMIT 1",
    "SELECT mobile FROM users LIMIT 1",
    "DELETE FROM facility_pulse WHERE false",
    "SELECT 1 FROM consent_records LIMIT 1",
    "SELECT 1 FROM lab_results LIMIT 0 FOR UPDATE",
    "UPDATE visits SET status = status WHERE false",
    "DELETE FROM admissions WHERE false",
    "INSERT INTO monitor_scopes (id, keycloak_sub, username, state_code, granted_by_sub) "
    "VALUES (gen_random_uuid(), 'x', 'x', 'BR', 'x')",
    "UPDATE audit_logs SET reason = reason WHERE false",
    "SELECT new_value FROM audit_logs LIMIT 1",
])
async def test_the_role_cannot_read_patients_or_change_clinical_data(db, statement):
    await _create_role(db)
    await db.execute(sa.text(f"SET ROLE {ROLE}"))
    savepoint = await db.begin_nested()
    with pytest.raises(DBAPIError) as refused:
        await db.execute(sa.text(statement))
    await savepoint.rollback()
    assert "permission denied" in str(refused.value.orig).lower()


async def test_the_role_has_no_login_until_one_is_given(db):
    await _create_role(db)
    can_login = (await db.execute(
        sa.text("SELECT rolcanlogin FROM pg_roles WHERE rolname = :r"), {"r": ROLE}
    )).scalar_one()
    assert can_login is False


async def test_running_the_file_twice_is_safe(db):
    await _create_role(db)
    await _create_role(db)
    roles = (await db.execute(sa.text("SELECT count(*) FROM pg_roles WHERE rolname = :r"), {"r": ROLE})).scalar_one()
    assert roles == 1

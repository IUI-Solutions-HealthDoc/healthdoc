"""tests/test_queue_service.py

Rewritten to match the current service.py: facility scoping on every
function, queue_counters for token_display, and the full priority
elevation rewrite (reason, tier-based roles, doctor/hod checks, MFA,
audit trail).

Run with: pytest tests/test_queue_service.py -v
"""
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.departments.models import Department
from app.notifications.models import NotificationHistory
from app.queue import service
from app.queue.models import QueueTokenPriorityChange
from app.users.models import User

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# Extra fixtures, built on top of conftest.py's db/seed/queue
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def hod_in_department(db, seed):
    """A user with the hod role's real-world shape: department_id set to
    the SAME department as the queue. Role itself ("hod") isn't stored
    on the user row -- it's passed directly as caller_roles in these
    tests, since we're calling service.py functions directly rather than
    going through a real JWT."""
    dept, _room, _doctor = seed
    user = User(
        id=uuid.uuid4(), keycloak_sub=f"hod-{uuid.uuid4()}", username=f"hod{uuid.uuid4().hex[:6]}",
        full_name="Dr. HOD", facility_id=dept.facility_id, department_id=dept.id,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def hod_in_other_department(db, seed):
    """Same idea, but department_id points at a DIFFERENT department --
    used to confirm hod is blocked from acting outside their own dept."""
    dept, _room, _doctor = seed
    other_dept = Department(id=uuid.uuid4(), code="OTH", name="Other Dept", facility_id=dept.facility_id)
    db.add(other_dept)
    await db.flush()
    user = User(
        id=uuid.uuid4(), keycloak_sub=f"hod-other-{uuid.uuid4()}", username=f"hodother{uuid.uuid4().hex[:6]}",
        full_name="Dr. Other HOD", facility_id=dept.facility_id, department_id=other_dept.id,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def other_doctor(db, seed):
    """A second doctor who does NOT own the test queue -- used to confirm
    doctor_recall is blocked for anyone but the queue's own doctor."""
    dept, _room, _doctor = seed
    user = User(
        id=uuid.uuid4(), keycloak_sub=f"otherdoc-{uuid.uuid4()}", username=f"otherdoc{uuid.uuid4().hex[:6]}",
        full_name="Dr. Other", facility_id=dept.facility_id,
    )
    db.add(user)
    await db.flush()
    return user


# --------------------------------------------------------------------------- #
# FACILITY SCOPING (Blocker 1)
# --------------------------------------------------------------------------- #

async def test_create_queue_derives_facility_from_department(db, seed):
    dept, room, doctor = seed
    from datetime import date
    queue = await service.create_queue(db, dept.id, doctor.id, room.id, "label", date.today(), dept.facility_id)
    assert queue.facility_id == dept.facility_id

async def test_create_queue_wrong_caller_facility_404(db, seed):
    """A caller at a different facility cannot create a queue for this
    department."""
    dept, room, doctor = seed
    from datetime import date
    other_facility_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await service.create_queue(db, dept.id, doctor.id, room.id, "label", date.today(), other_facility_id)
    assert exc.value.status_code == 404

async def test_create_token_wrong_facility_404(db, queue):
    other_facility_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await service.create_token(db, queue.id, uuid.uuid4(), "normal", other_facility_id)
    assert exc.value.status_code == 404


async def test_list_queue_tokens_wrong_facility_404(db, queue):
    other_facility_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await service.list_queue_tokens(db, queue.id, other_facility_id)
    assert exc.value.status_code == 404


# --------------------------------------------------------------------------- #
# QUEUE_COUNTERS (Blocker 3) -- the actual "two doctors, same number" fix
# --------------------------------------------------------------------------- #

async def test_token_display_sequence_within_one_queue(db, queue):
    t1 = await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)
    t2 = await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)
    assert t1.token_display.endswith("-001")
    assert t2.token_display.endswith("-002")


async def test_two_doctors_same_department_share_counter_no_collision(db, seed):
    """THE core Blocker 3 test. Two different doctors, same department,
    same day -- their tokens must NOT both be "-001"."""
    from datetime import date
    dept, room, doctor_a = seed

    doctor_b = User(
        id=uuid.uuid4(), keycloak_sub=f"docb-{uuid.uuid4()}", username=f"docb{uuid.uuid4().hex[:6]}",
        full_name="Dr. B", facility_id=dept.facility_id,
    )
    db.add(doctor_b)
    await db.flush()

    queue_a = await service.create_queue(db, dept.id, doctor_a.id, room.id, "Queue A", date.today(), dept.facility_id)
    queue_b = await service.create_queue(db, dept.id, doctor_b.id, room.id, "Queue B", date.today(), dept.facility_id)
 
    tok_a = await service.create_token(db, queue_a.id, uuid.uuid4(), "normal", queue_a.facility_id)
    tok_b = await service.create_token(db, queue_b.id, uuid.uuid4(), "normal", queue_b.facility_id)
    
    assert tok_a.token_display != tok_b.token_display
    assert tok_a.token_display.endswith("-001")
    assert tok_b.token_display.endswith("-002")  # shares dept.'s counter, not queue_a's


# --------------------------------------------------------------------------- #
# CALL NEXT / STUCK TOKEN (unchanged logic, re-verified against new code)
# --------------------------------------------------------------------------- #

async def test_call_next_respects_priority_over_age(db, queue):
    await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)
    emergency_tok = await service.create_token(db, queue.id, uuid.uuid4(), "emergency", queue.facility_id)
    called, _pending_event = await service.call_next_token(db, queue.id, queue.facility_id)
    assert called.id == emergency_tok.id


async def test_call_next_wrong_facility_404(db, queue):
    await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)
    with pytest.raises(HTTPException) as exc:
        await service.call_next_token(db, queue.id, uuid.uuid4())
    assert exc.value.status_code == 404


async def test_call_next_returns_pending_event_with_no_pii(db, queue):
    await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)
    called, pending_event = await service.call_next_token(db, queue.id, queue.facility_id)
 
    assert pending_event is not None
    assert pending_event["event_type"] == "token_called"
    assert pending_event["channel"] == f"queue:{queue.department_id}"
    payload = pending_event["payload"]
    assert set(payload.keys()) == {
        "department_id", "queue_id", "doctor_name", "room_number", "token_display", "now_serving",
    }
    assert payload["token_display"] == called.token_display
 
    rows = (await db.execute(select(NotificationHistory))).scalars().all()
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# PRIORITY ELEVATION (Blocker 4) -- reason, tier authority, audit trail
# --------------------------------------------------------------------------- #

async def test_elevate_priority_requires_reason(db, queue):
    tok = await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)
    with pytest.raises(HTTPException) as exc:
        await service.elevate_priority(
            db, tok.id, "emergency", "short", caller_sub="x", caller_roles=["doctor"],
            caller_amr=[], caller_facility_id=queue.facility_id,
        )
    assert exc.value.status_code == 422


async def test_elevate_priority_rejects_same_priority(db, queue, seed):
    _dept, _room, doctor = seed
    tok = await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)
    with pytest.raises(HTTPException) as exc:
        await service.elevate_priority(
            db, tok.id, "normal", "no actual change requested here",
            caller_sub=doctor.keycloak_sub, caller_roles=["doctor"],
            caller_amr=[], caller_facility_id=queue.facility_id,
        )
    assert exc.value.status_code == 422


async def test_elevate_priority_receptionist_can_set_senior_citizen(db, queue):
    tok = await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)
    # receptionist has no department_id requirement for this tier
    fake_receptionist_sub = f"recep-{uuid.uuid4()}"
    from app.users.models import User as UserModel
    recep = UserModel(
        id=uuid.uuid4(), keycloak_sub=fake_receptionist_sub, username=f"r{uuid.uuid4().hex[:6]}",
        full_name="Recep", facility_id=queue.facility_id,
    )
    db.add(recep)
    await db.flush()

    updated = await service.elevate_priority(
        db, tok.id, "senior_citizen", "confirmed senior citizen at registration desk",
        caller_sub=fake_receptionist_sub, caller_roles=["receptionist"],
        caller_amr=[], caller_facility_id=queue.facility_id,
    )
    assert updated.priority == "senior_citizen"


async def test_elevate_priority_receptionist_cannot_set_emergency(db, queue, seed):
    tok = await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)
    with pytest.raises(HTTPException) as exc:
        await service.elevate_priority(
            db, tok.id, "emergency", "patient looks critically unwell",
            caller_sub="whoever", caller_roles=["receptionist"],
            caller_amr=[], caller_facility_id=queue.facility_id,
        )
    assert exc.value.status_code == 403


async def test_elevate_priority_doctor_recall_requires_own_doctor(db, queue, seed, other_doctor):
    _dept, _room, owning_doctor = seed
    tok = await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)

    # The OTHER doctor (not this queue's own) tries to set doctor_recall.
    with pytest.raises(HTTPException) as exc:
        await service.elevate_priority(
            db, tok.id, "doctor_recall", "results just came back, need them now",
            caller_sub=other_doctor.keycloak_sub, caller_roles=["doctor"],
            caller_amr=[], caller_facility_id=queue.facility_id,
        )
    assert exc.value.status_code == 403

    # The queue's own doctor succeeds with the exact same request.
    updated = await service.elevate_priority(
        db, tok.id, "doctor_recall", "results just came back, need them now",
        caller_sub=owning_doctor.keycloak_sub, caller_roles=["doctor"],
        caller_amr=[], caller_facility_id=queue.facility_id,
    )
    assert updated.priority == "doctor_recall"


async def test_elevate_priority_admin_override_requires_hod_and_mfa(db, queue, hod_in_department):
    tok = await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)

    # hod, right department, but NO MFA -- rejected.
    with pytest.raises(HTTPException) as exc:
        await service.elevate_priority(
            db, tok.id, "admin_override", "VIP protocol per facility policy",
            caller_sub=hod_in_department.keycloak_sub, caller_roles=["hod"],
            caller_amr=[], caller_facility_id=queue.facility_id,
        )
    assert exc.value.status_code == 403

    # hod, right department, WITH MFA -- succeeds.
    updated = await service.elevate_priority(
        db, tok.id, "admin_override", "VIP protocol per facility policy",
        caller_sub=hod_in_department.keycloak_sub, caller_roles=["hod"],
        caller_amr=["otp"], caller_facility_id=queue.facility_id,
    )
    assert updated.priority == "admin_override"


async def test_elevate_priority_admin_override_wrong_department_blocked(db, queue, hod_in_other_department):
    tok = await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)
    with pytest.raises(HTTPException) as exc:
        await service.elevate_priority(
            db, tok.id, "admin_override", "VIP protocol per facility policy",
            caller_sub=hod_in_other_department.keycloak_sub, caller_roles=["hod"],
            caller_amr=["otp"], caller_facility_id=queue.facility_id,
        )
    assert exc.value.status_code == 403


async def test_elevate_priority_demote_requires_hod(db, queue, seed, hod_in_department):
    _dept, _room, doctor = seed
    tok = await service.create_token(db, queue.id, uuid.uuid4(), "emergency", queue.facility_id)

    # A doctor tries to demote emergency -> normal. Blocked.
    with pytest.raises(HTTPException) as exc:
        await service.elevate_priority(
            db, tok.id, "normal", "this was flagged emergency by mistake",
            caller_sub=doctor.keycloak_sub, caller_roles=["doctor"],
            caller_amr=[], caller_facility_id=queue.facility_id,
        )
    assert exc.value.status_code == 403

    # hod, same department, demotes successfully.
    updated = await service.elevate_priority(
        db, tok.id, "normal", "this was flagged emergency by mistake",
        caller_sub=hod_in_department.keycloak_sub, caller_roles=["hod"],
        caller_amr=[], caller_facility_id=queue.facility_id,
    )
    assert updated.priority == "normal"


async def test_elevate_priority_only_waiting_tokens(db, queue, seed):
    _dept, _room, doctor = seed
    tok = await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)
    await service.call_next_token(db, queue.id, queue.facility_id)  # now 'called', not 'waiting'

    with pytest.raises(HTTPException) as exc:
        await service.elevate_priority(
            db, tok.id, "emergency", "trying to elevate after being called",
            caller_sub=doctor.keycloak_sub, caller_roles=["doctor"],
            caller_amr=[], caller_facility_id=queue.facility_id,
        )
    assert exc.value.status_code == 409


async def test_elevate_priority_writes_audit_row(db, queue, seed):
    _dept, _room, doctor = seed
    tok = await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)

    await service.elevate_priority(
        db, tok.id, "doctor_recall", "results just came back, need them now",
        caller_sub=doctor.keycloak_sub, caller_roles=["doctor"],
        caller_amr=[], caller_facility_id=queue.facility_id,
    )

    rows = (
        await db.execute(select(QueueTokenPriorityChange).where(QueueTokenPriorityChange.queue_token_id == tok.id))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].from_priority == "normal"
    assert rows[0].to_priority == "doctor_recall"
    assert rows[0].changed_by == doctor.id
    assert "results just came back" in rows[0].reason


async def test_elevate_priority_initial_priority_unchanged_after_elevation(db, queue, seed):
    """initial_priority records what the token was ISSUED at, and must
    NOT change even after priority is elevated."""
    _dept, _room, doctor = seed
    tok = await service.create_token(db, queue.id, uuid.uuid4(), "normal", queue.facility_id)
    assert tok.initial_priority == "normal"

    updated = await service.elevate_priority(
        db, tok.id, "emergency", "condition suddenly worsened in the waiting room",
        caller_sub=doctor.keycloak_sub, caller_roles=["emergency"],
        caller_amr=[], caller_facility_id=queue.facility_id,
    )
    assert updated.priority == "emergency"
    assert updated.initial_priority == "normal"  # unchanged
    

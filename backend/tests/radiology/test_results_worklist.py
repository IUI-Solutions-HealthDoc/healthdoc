"""GET /orders/results-worklist — the doctor's outstanding results.

The screen that answers "what have I ordered, what has come back, and what
needs my sign-off". It had no backend. The frontend fixture's own docstring
described it as "backed by GET /pathology/order-items and
GET /radiology/order-items, joined with each item's current result" — a join
across two modules that no endpoint performed.

Run through HTTP against real PostgreSQL rather than the shared `db` fixture.
The implementation is a raw CTE union using NULLS LAST and a conditional join;
the shared fixture is in-memory SQLite built from ORM metadata, so a test there
would prove almost nothing about the query that ships. Same blind spot that hid
the queue-token index bug.

TWO THINGS THE FIRST VERSION OF THIS FILE GOT WRONG — both worth keeping here.

1. `client_as` returns ONE TestClient and swaps a dependency override. Calling
   it three times does not give three identities; the last call wins for every
   subsequent request. Holding `doc`, `rad` and `tech` handles at the top of a
   test silently ran the whole test as the tech, which surfaced as a 403 on a
   doctor-only route. Switch identity immediately before each request.

2. `seed_order_chain` inserts a fixed ORDER_ID with ON CONFLICT DO NOTHING,
   while this suite's DOCTOR.sub is a fresh uuid4() per run. On any run after
   the first, the seeded order keeps the PREVIOUS run's created_by — so a test
   that scopes on ownership passes once and then fails forever. These tests
   therefore create their own order through POST /orders, whose created_by now
   comes from the token.
"""
from tests._lab_seed import ENCOUNTER_ID, PATIENT_ID
from tests.radiology.conftest import DOCTOR, RADIOLOGIST, RADIOLOGY_TECH


def _worklist(client):
    response = client.get("/api/v1/orders/results-worklist")
    assert response.status_code == 200, response.text
    return response.json()["data"]["items"]


def _new_order(client) -> str:
    """An order owned by whoever the client is currently acting as."""
    response = client.post(
        "/api/v1/orders",
        json={
            "encounter_id": str(ENCOUNTER_ID),
            "patient_id": str(PATIENT_ID),
            "order_type": "radiology",
            "priority": "routine",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _new_scan(client, order_id: str, *, scan_type: str = "Chest X-Ray") -> dict:
    response = client.post(
        f"/api/v1/radiology/order-items?order_id={order_id}",
        json={"modality": "xray", "scan_type": scan_type},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_a_placed_scan_appears_with_no_result_yet(client_as, seeded_order_id):
    """"Ordered, not back yet" is the state most of this list is in, and it has
    to be distinguishable from "reported"."""
    doc = client_as(DOCTOR)
    item = _new_scan(doc, _new_order(doc))

    mine = next((r for r in _worklist(doc) if r["id"] == item["id"]), None)

    assert mine is not None, "a scan this doctor ordered must appear on their worklist"
    assert mine["order_type"] == "radiology"
    assert mine["result_status"] is None, "no report filed yet"
    assert mine["reported_at"] is None
    assert mine["review_status"] is None, "no review opened yet"


def test_the_worklist_carries_the_encounter_id(client_as, seeded_order_id):
    """doctor_reviews belong to an encounter, so a screen opening a review from
    this list needs it. The fixture omitted encounter_id, which is why its
    review lifecycle had to file everything against one hardcoded encounter."""
    doc = client_as(DOCTOR)
    item = _new_scan(doc, _new_order(doc), scan_type="CT Head")

    mine = next(r for r in _worklist(doc) if r["id"] == item["id"])

    assert mine["encounter_id"] == str(ENCOUNTER_ID)


def test_patient_identity_is_joined_not_left_to_the_client(client_as, seeded_order_id):
    """Asserted on a specific row, not with all() over the list — all() over an
    empty list is vacuously true, which is how the first version of this file
    reported a pass while the endpoint returned nothing at all."""
    doc = client_as(DOCTOR)
    item = _new_scan(doc, _new_order(doc), scan_type="USG Abdomen")

    mine = next(r for r in _worklist(doc) if r["id"] == item["id"])

    assert mine["patient_name"], "patients is joined server-side"
    assert mine["uhid"], (
        "COALESCE(uhid, thid) — an emergency THID-only patient still needs an "
        "identifier on a results list"
    )


def test_a_reported_scan_shows_as_reported(client_as, seeded_order_id):
    """The half the screen exists for: the result came back.

    Identity is switched immediately before each request rather than held as
    separate handles — see the module docstring.
    """
    doc = client_as(DOCTOR)
    item = _new_scan(doc, _new_order(doc), scan_type="Chest X-Ray PA")

    tech = client_as(RADIOLOGY_TECH)
    # Schedule first, and ASSERT both calls. This test previously fired
    # scan-complete with no assertion at all: it was 409ing every run (nothing
    # could set 'scheduled') and still passing, because drafting a report does
    # not check the item's status. A silent 409 inside a green test.
    scheduled = tech.put(
        f"/api/v1/radiology/order-items/{item['id']}/schedule",
        json={"scheduled_at": "2027-02-01T10:00:00Z", "machine_id": "XR-01"},
    )
    assert scheduled.status_code == 200, scheduled.text
    completed = tech.put(
        f"/api/v1/radiology/order-items/{item['id']}/scan-complete", json={},
    )
    assert completed.status_code == 200, completed.text

    rad = client_as(RADIOLOGIST)
    drafted = rad.post(
        f"/api/v1/radiology/order-items/{item['id']}/reports",
        json={"findings": "No focal consolidation.", "impression": "Normal study."},
    )
    assert drafted.status_code == 201, drafted.text

    doc = client_as(DOCTOR)
    mine = next(r for r in _worklist(doc) if r["id"] == item["id"])

    assert mine["result_status"] == "preliminary"
    assert mine["reported_at"] is not None


def test_another_doctors_orders_are_not_on_this_worklist(client_as, seeded_order_id):
    """Scope follows queue.service.get_doctor_worklist: a doctor sees their own.

    RADIOLOGIST carries roles=["doctor"] with a different sub, so a different
    users.id — a genuine second doctor, not a role difference.
    """
    doc = client_as(DOCTOR)
    item = _new_scan(doc, _new_order(doc), scan_type="MRI Brain")

    other = client_as(RADIOLOGIST)
    rows = _worklist(other)

    assert all(r["id"] != item["id"] for r in rows), (
        "a doctor must not see orders another doctor placed"
    )


def test_the_endpoint_is_not_captured_by_the_order_id_route(client_as, seeded_order_id):
    """/orders/results-worklist and /orders/{order_id} are both one segment
    under /orders. Registered the wrong way round, 'results-worklist' is parsed
    as a UUID and this 422s — a routing bug that reads as a validation one."""
    doc = client_as(DOCTOR)
    response = doc.get("/api/v1/orders/results-worklist")

    assert response.status_code == 200, (
        f"expected the worklist route, got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------- scheduling

def test_the_workflow_was_broken_at_its_first_step(client_as, seeded_order_id):
    """A placed scan could not be marked complete, because nothing scheduled it.

    ScheduleRequest existed as a schema and was imported by the router; no route
    used it. Items are created 'placed', mark_scan_complete refuses anything not
    'scheduled', and nothing set that status — so the radiology workflow stopped
    at step one. Same shape as billing's draft -> issued gap.
    """
    doc = client_as(DOCTOR)
    item = _new_scan(doc, _new_order(doc), scan_type="CT Abdomen")

    tech = client_as(RADIOLOGY_TECH)

    # Before scheduling, completing is refused — this is what used to be a
    # permanent dead end.
    premature = tech.put(
        f"/api/v1/radiology/order-items/{item['id']}/scan-complete", json={},
    )
    assert premature.status_code == 409, premature.text

    scheduled = tech.put(
        f"/api/v1/radiology/order-items/{item['id']}/schedule",
        json={
            "scheduled_at": "2027-01-04T09:30:00Z",
            "machine_id": "CT-01",
        },
    )
    assert scheduled.status_code == 200, scheduled.text
    body = scheduled.json()["data"]
    assert body["status"] == "scheduled"
    assert body["machine_id"] == "CT-01"

    # And now the step that was unreachable works.
    completed = tech.put(
        f"/api/v1/radiology/order-items/{item['id']}/scan-complete", json={},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["status"] == "scanned"


def test_a_scan_cannot_be_booked_into_the_past(client_as, seeded_order_id):
    """A slot in the past is a data-entry error, and it would sort a scan into
    a worklist window that has already closed."""
    doc = client_as(DOCTOR)
    item = _new_scan(doc, _new_order(doc), scan_type="USG Pelvis")

    tech = client_as(RADIOLOGY_TECH)
    response = tech.put(
        f"/api/v1/radiology/order-items/{item['id']}/schedule",
        json={"scheduled_at": "2020-01-01T09:00:00Z", "machine_id": "USG-01"},
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["message"]["code"] == "scheduled_in_the_past"


def test_only_a_placed_scan_can_be_scheduled(client_as, seeded_order_id):
    """Re-scheduling is a different operation — it has to say what happened to
    the original slot — so it is refused rather than silently invented."""
    doc = client_as(DOCTOR)
    item = _new_scan(doc, _new_order(doc), scan_type="MRI Spine")

    tech = client_as(RADIOLOGY_TECH)
    slot = {"scheduled_at": "2027-01-05T11:00:00Z", "machine_id": "MRI-01"}
    assert tech.put(f"/api/v1/radiology/order-items/{item['id']}/schedule", json=slot).status_code == 200

    again = tech.put(f"/api/v1/radiology/order-items/{item['id']}/schedule", json=slot)
    assert again.status_code == 409, again.text


def test_scheduled_scan_can_be_rescheduled_with_a_reason(client_as, seeded_order_id):
    doc = client_as(DOCTOR)
    item = _new_scan(doc, _new_order(doc), scan_type="CT Chest")
    tech = client_as(RADIOLOGY_TECH)
    assert tech.put(
        f"/api/v1/radiology/order-items/{item['id']}/schedule",
        json={"scheduled_at": "2099-01-05T11:00:00Z", "machine_id": "CT-01"},
    ).status_code == 200

    response = tech.put(
        f"/api/v1/radiology/order-items/{item['id']}/reschedule",
        json={
            "scheduled_at": "2099-01-06T12:30:00Z",
            "machine_id": "CT-02",
            "reason": "Machine CT-01 is under maintenance",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["status"] == "scheduled"
    assert body["machine_id"] == "CT-02"
    assert body["scheduled_at"].startswith("2099-01-06T12:30:00")


def test_unperformed_scan_can_be_cancelled_but_completed_work_cannot(
    client_as, seeded_order_id
):
    doc = client_as(DOCTOR)
    item = _new_scan(doc, _new_order(doc), scan_type="MRI Knee")
    tech = client_as(RADIOLOGY_TECH)

    cancelled = tech.put(
        f"/api/v1/radiology/order-items/{item['id']}/cancel",
        json={"reason": "Patient withdrew consent before imaging"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "cancelled"

    complete = tech.put(
        f"/api/v1/radiology/order-items/{item['id']}/scan-complete", json={}
    )
    assert complete.status_code == 409, complete.text


def test_cancel_and_reschedule_reasons_are_validated(client_as, seeded_order_id):
    doc = client_as(DOCTOR)
    item = _new_scan(doc, _new_order(doc), scan_type="USG Renal")
    tech = client_as(RADIOLOGY_TECH)

    too_short = tech.put(
        f"/api/v1/radiology/order-items/{item['id']}/cancel",
        json={"reason": "no"},
    )
    assert too_short.status_code == 422, too_short.text

    naive_time = tech.put(
        f"/api/v1/radiology/order-items/{item['id']}/schedule",
        json={"scheduled_at": "2099-01-05T11:00:00", "machine_id": "USG-01"},
    )
    assert naive_time.status_code == 422, naive_time.text

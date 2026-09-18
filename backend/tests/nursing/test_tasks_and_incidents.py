"""Nurse task check-off (#210) and the clinical incident register (#236).

Both were blockers for Ankit's screens. The behaviours pinned here are the ones
that make the records trustworthy rather than merely present:

  * a check-off records WHO and WHEN, and cannot be silently overwritten
  * status and evidence cannot disagree
  * an incident can exist without a patient
  * a closed incident must say what was found and what changed
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.common.enums import (
    ClinicalIncidentSeverity, ClinicalIncidentStatus, ClinicalIncidentType, OrderStatus,
)
from app.nursing import incidents as inc
from app.nursing.schemas import IncidentReport, IncidentReviewRequest
from app.nursing.service import (
    DiagnosticOrderRequiresFulfillment,
    OrderAlreadyCompleted,
    OrderCancelledError,
    OrderNotFound,
    accept_order,
    complete_order,
    pending_orders,
)
from app.orders.models import Order

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)


async def _order(db, *, status=OrderStatus.PLACED.value, order_type="procedure", patient_id=None):
    order = Order(
        id=uuid.uuid4(),
        order_number=f"ORD-{uuid.uuid4().hex[:10]}",
        encounter_id=uuid.uuid4(),
        patient_id=patient_id or uuid.uuid4(),
        facility_id=uuid.uuid4(),
        order_type=order_type,
        priority="routine",
        status=status,
        ordered_at=NOW,
        created_by=uuid.uuid4(),
    )
    db.add(order)
    await db.flush()
    return order


# ---------------------------------------------------------------- task queue (#210)

async def test_queue_shows_open_orders_and_hides_finished_ones(db):
    patient_id = uuid.uuid4()
    await _order(db, status=OrderStatus.PLACED.value, patient_id=patient_id)
    await _order(db, status=OrderStatus.IN_PROGRESS.value, patient_id=patient_id)
    await _order(db, status=OrderStatus.CANCELLED.value, patient_id=patient_id)

    open_orders = await pending_orders(db, patient_id=patient_id)
    statuses = {o.status for o in open_orders}

    assert statuses == {"placed", "in_progress"}, "cancelled orders are not tasks"


async def test_queue_can_be_filtered_by_order_type(db):
    patient_id = uuid.uuid4()
    await _order(db, order_type="lab", patient_id=patient_id)
    await _order(db, order_type="radiology", patient_id=patient_id)

    lab_only = await pending_orders(db, patient_id=patient_id, order_type="lab")
    assert [o.order_type for o in lab_only] == ["lab"]


async def test_completing_records_who_and_when(db):
    """The point of #210: status alone said THAT it was done."""
    order = await _order(db)
    nurse = uuid.uuid4()

    done = await complete_order(db, order.id, completed_by=nurse, note="given with food")

    assert done.status == OrderStatus.COMPLETED.value
    assert done.completed_by == nurse
    assert done.completed_at is not None
    assert done.completion_note == "given with food"


async def test_completing_implies_acceptance(db):
    """An order completed without a separate accept step was still picked up.

    Leaving accepted_at NULL would lose that it was ever taken on, and the ward
    could not tell a fast completion from one that skipped triage.
    """
    order = await _order(db)
    done = await complete_order(db, order.id, completed_by=uuid.uuid4())

    assert done.accepted_at is not None
    assert done.accepted_at == done.completed_at


async def test_accepting_is_idempotent_and_keeps_the_first_actor(db):
    """The first acceptance is the one that says when the ward picked it up."""
    order = await _order(db)
    first, second = uuid.uuid4(), uuid.uuid4()

    once = await accept_order(db, order.id, accepted_by=first)
    twice = await accept_order(db, order.id, accepted_by=second)

    assert twice.accepted_by == first
    assert twice.accepted_at == once.accepted_at


async def test_accepting_moves_placed_to_accepted(db):
    order = await _order(db, status=OrderStatus.PLACED.value)
    accepted = await accept_order(db, order.id, accepted_by=uuid.uuid4())
    assert accepted.status == OrderStatus.ACCEPTED.value


async def test_re_completing_is_refused(db):
    """A second check-off would overwrite the first timestamp and actor, and in
    a dispute about when something was done the original is the only entry that
    matters."""
    order = await _order(db)
    await complete_order(db, order.id, completed_by=uuid.uuid4())

    with pytest.raises(OrderAlreadyCompleted):
        await complete_order(db, order.id, completed_by=uuid.uuid4())


async def test_unknown_order_raises(db):
    with pytest.raises(OrderNotFound):
        await complete_order(db, uuid.uuid4(), completed_by=uuid.uuid4())


# ---------------------------------------------------------------- incidents (#236)

def _report(**over):
    base = dict(
        incident_type=ClinicalIncidentType.PATIENT_FALL.value,
        severity=ClinicalIncidentSeverity.MINOR.value,
        occurred_at=NOW,
        description="Patient slipped beside the bed while unassisted.",
        immediate_action="Assessed for injury, no fracture, doctor informed.",
    )
    base.update(over)
    return IncidentReport(**base)


async def test_reported_incident_starts_in_reported(db):
    facility_id, nurse = uuid.uuid4(), uuid.uuid4()
    incident = await inc.report_incident(
        db, facility_id=facility_id, reported_by=nurse,
        **_report().model_dump(exclude_none=False))

    assert incident.status == ClinicalIncidentStatus.REPORTED.value
    assert incident.reported_by == nurse
    assert incident.reviewed_at is None


async def test_an_incident_can_have_no_patient(db):
    """A sharps injury to staff, or equipment found faulty before use, is
    reportable and has no patient. Requiring one would push staff to attribute
    incidents to whoever happened to be nearby."""
    incident = await inc.report_incident(
        db, facility_id=uuid.uuid4(), reported_by=uuid.uuid4(),
        **_report(incident_type=ClinicalIncidentType.NEEDLESTICK.value,
                  patient_id=None).model_dump(exclude_none=False))

    assert incident.patient_id is None


async def test_near_miss_is_a_type_not_a_severity():
    """An event that reached the patient with no harm is a different fact from
    one that never reached them. Collapsing them hides the first — the one that
    says a barrier failed late rather than early."""
    assert "near_miss" in ClinicalIncidentType.values()
    assert "near_miss" not in ClinicalIncidentSeverity.values()

    ok = _report(incident_type=ClinicalIncidentType.NEAR_MISS.value,
                 severity=ClinicalIncidentSeverity.NO_HARM.value)
    assert ok.severity == "no_harm"


async def test_reporting_before_it_happened_is_rejected():
    with pytest.raises(ValidationError):
        _report(occurred_at=NOW, reported_at=NOW - timedelta(hours=1))


async def test_unknown_type_or_severity_is_rejected():
    with pytest.raises(ValidationError):
        _report(incident_type="patient_tripped")
    with pytest.raises(ValidationError):
        _report(severity="catastrophic")


async def test_closing_requires_a_root_cause_and_a_corrective_action(db):
    """A register of closed incidents with no findings teaches nobody anything."""
    incident = await inc.report_incident(
        db, facility_id=uuid.uuid4(), reported_by=uuid.uuid4(),
        **_report().model_dump(exclude_none=False))

    with pytest.raises(inc.IncidentClosureIncomplete):
        await inc.review_incident(
            db, incident.id, status=ClinicalIncidentStatus.CLOSED.value,
            reviewed_by=uuid.uuid4())

    with pytest.raises(inc.IncidentClosureIncomplete):
        await inc.review_incident(
            db, incident.id, status=ClinicalIncidentStatus.CLOSED.value,
            reviewed_by=uuid.uuid4(), root_cause="Wet floor", corrective_action="   ")


async def test_closing_with_findings_succeeds_and_records_the_reviewer(db):
    incident = await inc.report_incident(
        db, facility_id=uuid.uuid4(), reported_by=uuid.uuid4(),
        **_report().model_dump(exclude_none=False))
    reviewer = uuid.uuid4()

    closed = await inc.review_incident(
        db, incident.id, status=ClinicalIncidentStatus.CLOSED.value,
        reviewed_by=reviewer,
        root_cause="Floor left wet after cleaning, no signage.",
        corrective_action="Wet-floor signage added to cleaning checklist.")

    assert closed.status == "closed"
    assert closed.reviewed_by == reviewer
    assert closed.reviewed_at is not None


async def test_moving_to_under_review_needs_no_findings_yet(db):
    """Only closure demands conclusions — an investigation has to be able to
    start before it has an answer."""
    incident = await inc.report_incident(
        db, facility_id=uuid.uuid4(), reported_by=uuid.uuid4(),
        **_report().model_dump(exclude_none=False))

    reviewing = await inc.review_incident(
        db, incident.id, status=ClinicalIncidentStatus.UNDER_REVIEW.value,
        reviewed_by=uuid.uuid4())
    assert reviewing.status == "under_review"
    assert reviewing.root_cause is None


async def test_register_is_scoped_to_its_facility(db):
    facility_a, facility_b = uuid.uuid4(), uuid.uuid4()
    await inc.report_incident(db, facility_id=facility_a, reported_by=uuid.uuid4(),
                              **_report().model_dump(exclude_none=False))

    assert len(await inc.list_incidents(db, facility_a)) == 1
    assert await inc.list_incidents(db, facility_b) == []


async def test_incidents_cannot_be_deleted():
    """An incident register that can be emptied is not a register."""
    from app.nursing.router import router

    incident_routes = [r for r in router.routes if "incidents" in getattr(r, "path", "")]
    assert incident_routes, "expected incident routes to exist"
    for route in incident_routes:
        assert "DELETE" not in getattr(route, "methods", set())


# ---------------------------------------------------------------- task safety guards

async def test_cancelled_order_cannot_be_accepted(db):
    order = await _order(db, status=OrderStatus.CANCELLED.value, order_type="procedure")
    with pytest.raises(OrderCancelledError):
        await accept_order(db, order.id, accepted_by=uuid.uuid4())


async def test_cancelled_order_cannot_be_completed(db):
    order = await _order(db, status=OrderStatus.CANCELLED.value, order_type="procedure")
    with pytest.raises(OrderCancelledError):
        await complete_order(db, order.id, completed_by=uuid.uuid4())


async def test_diagnostic_order_cannot_be_generic_completed(db):
    for diag_type in ("lab", "radiology"):
        order = await _order(db, status=OrderStatus.PLACED.value, order_type=diag_type)
        with pytest.raises(DiagnosticOrderRequiresFulfillment) as exc_info:
            await complete_order(db, order.id, completed_by=uuid.uuid4())
        assert exc_info.value.order_type == diag_type


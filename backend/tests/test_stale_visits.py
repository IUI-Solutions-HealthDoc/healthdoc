"""HD-12: Stale visit reconciliation tests."""

import uuid
from datetime import date, datetime, timezone
import pytest
from pydantic import ValidationError

from app.queue.schemas import (
    StaleVisitCandidateOut,
    StaleVisitsReconcileRequest,
    StaleVisitsReconcileResult,
    StaleVisitsReportOut,
)


def test_stale_visit_candidate_schema():
    v_id = uuid.uuid4()
    p_id = uuid.uuid4()
    c = StaleVisitCandidateOut(
        visit_id=v_id,
        visit_number="VIS-20260901-0001",
        patient_id=p_id,
        patient_name="Sita Devi",
        patient_uhid="IN-DL-AIIMS-2026-000001-4",
        visit_date=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
        current_status="registered",
        recommended_visit_action="mark_lwbs",
        recommended_token_action="mark_no_show",
    )
    assert c.visit_number == "VIS-20260901-0001"
    assert c.current_status == "registered"
    assert c.recommended_visit_action == "mark_lwbs"


def test_stale_visits_report_schema():
    rep = StaleVisitsReportOut(
        total_stale_count=0,
        cutoff_date=date(2026, 9, 18),
        candidates=[],
    )
    assert rep.total_stale_count == 0
    assert rep.cutoff_date == date(2026, 9, 18)


def test_stale_visits_reconcile_schemas():
    v1 = uuid.uuid4()
    req = StaleVisitsReconcileRequest(visit_ids=[v1], reason="Daily review reconciliation")
    assert req.visit_ids == [v1]
    assert req.reason == "Daily review reconciliation"

    res = StaleVisitsReconcileResult(
        reconciled_count=1,
        skipped_count=0,
        reconciled_visits=[v1],
        skipped_details=[],
    )
    assert res.reconciled_count == 1
    assert res.reconciled_visits == [v1]

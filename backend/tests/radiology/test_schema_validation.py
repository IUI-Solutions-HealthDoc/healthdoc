"""Validation that protects radiology workflow and audit history inputs."""

import pytest
from pydantic import ValidationError

from app.radiology.schemas import (
    CancelScanRequest,
    RadiologyReportCreate,
    RescheduleRequest,
    ScheduleRequest,
)


def test_schedule_requires_an_aware_future_candidate_and_nonblank_machine():
    with pytest.raises(ValidationError):
        ScheduleRequest(scheduled_at="2099-01-01T10:00:00", machine_id="CT-01")
    with pytest.raises(ValidationError):
        ScheduleRequest(scheduled_at="2099-01-01T10:00:00Z", machine_id="   ")


def test_cancel_and_reschedule_reasons_cannot_be_blank_padding():
    with pytest.raises(ValidationError):
        CancelScanRequest(reason="     ")
    with pytest.raises(ValidationError):
        RescheduleRequest(
            scheduled_at="2099-01-01T10:00:00Z",
            machine_id="CT-01",
            reason="     ",
        )


def test_report_narratives_cannot_be_empty():
    with pytest.raises(ValidationError):
        RadiologyReportCreate(findings="   ", impression="Normal")
    with pytest.raises(ValidationError):
        RadiologyReportCreate(findings="Normal", impression="   ")

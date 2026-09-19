"""Schemas for transactional outbox and dead-letter queue (HD-31)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class OutboxEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    aggregate_type: str
    aggregate_id: uuid.UUID
    event_type: str
    sensitivity: str
    status: str
    attempts: int
    last_error: str | None
    sent_at: datetime | None
    sequence: int
    created_at: datetime


class OutboxDeadLetterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_event_id: uuid.UUID | None
    aggregate_type: str
    aggregate_id: uuid.UUID
    event_type: str
    payload_redacted: dict[str, Any]
    error_message: str
    failed_at: datetime
    replay_count: int
    created_at: datetime


class OutboxMetricsOut(BaseModel):
    pending_count: int
    in_flight_count: int
    sent_count: int
    dead_letter_count: int
    total_events: int
    delivery_lag_seconds: float

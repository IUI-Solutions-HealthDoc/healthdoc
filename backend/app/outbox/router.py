"""Outbox and dead-letter queue operations router (HD-31)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, DbSession, require_roles
from app.outbox import service
from app.outbox.schemas import OutboxDeadLetterOut, OutboxEventOut, OutboxMetricsOut

router = APIRouter(prefix="/outbox", tags=["outbox"])


@router.get(
    "/events",
    response_model=list[OutboxEventOut],
    dependencies=[Depends(require_roles("admin", "auditor"))],
)
async def list_outbox_events(
    db: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    aggregate_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[OutboxEventOut]:
    """List recent transactional outbox events with delivery status and attempts."""
    events = await service.list_events(db, status_filter=status_filter, aggregate_type=aggregate_type, limit=limit)
    return [OutboxEventOut.model_validate(e) for e in events]


@router.get(
    "/dead-letter",
    response_model=list[OutboxDeadLetterOut],
    dependencies=[Depends(require_roles("admin", "auditor"))],
)
async def list_dead_letter_queue(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[OutboxDeadLetterOut]:
    """List failed events in dead-letter queue with redacted clinical/PHI payloads."""
    dls = await service.list_dead_letters(db, limit=limit)
    return [OutboxDeadLetterOut.model_validate(d) for d in dls]


@router.post(
    "/dead-letter/{id}/replay",
    response_model=OutboxEventOut,
    dependencies=[Depends(require_roles("admin"))],
)
async def replay_dead_letter_event(
    id: uuid.UUID,
    db: DbSession,
) -> OutboxEventOut:
    """Replay an exhausted dead-letter event by re-enqueuing into outbox_events with status='pending'."""
    try:
        ev = await service.replay_dead_letter(db, str(id))
        return OutboxEventOut.model_validate(ev)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/metrics",
    response_model=OutboxMetricsOut,
    dependencies=[Depends(require_roles("admin", "auditor"))],
)
async def get_outbox_metrics(
    db: DbSession,
) -> OutboxMetricsOut:
    """Retrieve transactional outbox metrics: queue depths, sent count, and delivery lag."""
    return OutboxMetricsOut.model_validate(await service.get_metrics(db))

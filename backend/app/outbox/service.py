"""Outbox producer + shipper (B1-W6-01).

Delivery guarantee: AT-LEAST-ONCE with idempotency key (the event UUID).
The receiver must deduplicate on event id.

Flow:
  1. enqueue() — called inside the SAME transaction as the business write
  2. ship_pending() — background worker:
     a. Claim rows (status='in_flight', committed) so crashes don't lose them
     b. Send to cloud (cloud_send receives the event id for deduplication)
     c. Mark 'sent' on ack, or increment attempts on failure
     d. Exhausted rows (max attempts) move to 'dead_letter' — no infinite retry

A failed publish NEVER rolls back the business write.

Run one shipper for streams that require sequence order. Concurrent shippers preserve
at-least-once delivery but can send unrelated unlocked rows out of sequence.
"""
from datetime import datetime, timezone
import json
import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox.models import OutboxDeadLetter, OutboxEvent

MAX_ATTEMPTS = 5


async def enqueue(db: AsyncSession, *, aggregate_type: str, aggregate_id: str,
                  event_type: str, payload: dict[str, Any], sensitivity: str = "normal") -> None:
    """Call inside the SAME transaction as the business write."""
    # CAST(... AS jsonb) is Postgres-only. Under SQLite it silently
    # coerces the JSON text to 0 (no numeric prefix -> NUMERIC affinity
    # -> 0), so this is dialect-gated rather than a bare literal.
    payload_expr = "CAST(:pl AS jsonb)" if db.bind.dialect.name == "postgresql" else ":pl"
    new_id = str(uuid.uuid4())
    await db.execute(text(f"""
        INSERT INTO outbox_events
            (id, aggregate_type, aggregate_id, event_type, payload, sensitivity, status, attempts)
        VALUES (:id, :at, :aid, :et, {payload_expr}, :sev, 'pending', 0)
    """), {"id": new_id, "at": aggregate_type, "aid": aggregate_id, "et": event_type,
           "pl": json.dumps(payload), "sev": sensitivity})


async def ship_pending(db: AsyncSession, cloud_send, batch: int = 100) -> int:
    """Worker step: claim → send → mark. At-least-once with idempotency key."""
    rows = (await db.execute(text("""
        UPDATE outbox_events
        SET status = 'in_flight', updated_at = now()
        WHERE id IN (
            SELECT id FROM outbox_events
            WHERE status = 'pending'
            ORDER BY sequence ASC
            LIMIT :n
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id, aggregate_type, aggregate_id, event_type, payload, sensitivity
    """), {"n": batch})).mappings().all()

    if not rows:
        return 0

    await db.commit()

    sent = 0
    for r in rows:
        row_dict = dict(r)
        ok = await cloud_send(row_dict)
        if ok:
            await db.execute(text("""
                UPDATE outbox_events
                SET status = 'sent', attempts = attempts + 1, sent_at = now(), updated_at = now()
                WHERE id = :id
            """), {"id": r["id"]})
            sent += 1
        else:
            await db.execute(text("""
                UPDATE outbox_events
                SET status = CASE
                        WHEN attempts + 1 >= :max THEN 'dead_letter'
                        ELSE 'pending'
                    END,
                    attempts = attempts + 1,
                    last_error = 'send failed at attempt ' || (attempts + 1)::text,
                    updated_at = now()
                WHERE id = :id
            """), {"id": r["id"], "max": MAX_ATTEMPTS})
        await db.commit()

    return sent


async def reap_stranded(db: AsyncSession, stale_minutes: int = 10) -> int:
    """Return in_flight rows older than `stale_minutes` back to pending."""
    result = await db.execute(text("""
        UPDATE outbox_events
        SET status = 'pending'
        WHERE status = 'in_flight'
          AND updated_at < now() - make_interval(mins => :mins)
        RETURNING id
    """), {"mins": stale_minutes})
    reaped = len(result.all())
    if reaped:
        await db.commit()
    return reaped


SENSITIVE_KEYS = {"password", "secret", "token", "otp", "aadhaar", "pan", "key", "authorization"}


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = {}
    for k, v in payload.items():
        if any(s in k.lower() for s in SENSITIVE_KEYS):
            redacted[k] = "[REDACTED]"
        elif isinstance(v, dict):
            redacted[k] = redact_payload(v)
        else:
            redacted[k] = v
    return redacted


async def list_events(
    db: AsyncSession,
    status_filter: str | None = None,
    aggregate_type: str | None = None,
    limit: int = 100,
) -> list[OutboxEvent]:
    query = select(OutboxEvent).order_by(OutboxEvent.sequence.desc()).limit(limit)
    if status_filter:
        query = query.where(OutboxEvent.status == status_filter.strip())
    if aggregate_type:
        query = query.where(OutboxEvent.aggregate_type == aggregate_type.strip())
    res = await db.execute(query)
    return list(res.scalars().all())


async def list_dead_letters(
    db: AsyncSession,
    limit: int = 100,
) -> list[OutboxDeadLetter]:
    res = await db.execute(
        select(OutboxDeadLetter).order_by(OutboxDeadLetter.failed_at.desc()).limit(limit)
    )
    return list(res.scalars().all())


async def replay_dead_letter(
    db: AsyncSession,
    dead_letter_id: uuid.UUID | str,
) -> OutboxEvent:
    uid = uuid.UUID(str(dead_letter_id))
    dl_res = await db.execute(select(OutboxDeadLetter).where(OutboxDeadLetter.id == uid))
    dl = dl_res.scalar_one_or_none()
    if not dl:
        raise ValueError(f"Dead letter record {dead_letter_id} not found")

    dl.replay_count += 1
    new_event = OutboxEvent(
        id=uuid.uuid4(),
        aggregate_type=dl.aggregate_type,
        aggregate_id=dl.aggregate_id,
        event_type=dl.event_type,
        payload=dl.payload_redacted,
        sensitivity="normal",
        status="pending",
        attempts=0,
    )
    db.add(new_event)
    await db.commit()
    await db.refresh(new_event)
    return new_event


async def get_metrics(db: AsyncSession) -> dict[str, Any]:
    pending_count = (await db.execute(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == "pending"))).scalar() or 0
    in_flight_count = (await db.execute(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == "in_flight"))).scalar() or 0
    sent_count = (await db.execute(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == "sent"))).scalar() or 0
    dl_count = (await db.execute(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == "dead_letter"))).scalar() or 0
    total_count = (await db.execute(select(func.count()).select_from(OutboxEvent))).scalar() or 0
    dl_table_count = (await db.execute(select(func.count()).select_from(OutboxDeadLetter))).scalar() or 0

    oldest_pending = (await db.execute(
        select(func.min(OutboxEvent.created_at)).where(OutboxEvent.status == "pending")
    )).scalar()
    lag_seconds = 0.0
    if oldest_pending:
        now_dt = datetime.now(timezone.utc)
        if oldest_pending.tzinfo is None:
            now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
        lag_seconds = max(0.0, (now_dt - oldest_pending).total_seconds())

    return {
        "pending_count": pending_count,
        "in_flight_count": in_flight_count,
        "sent_count": sent_count,
        "dead_letter_count": max(dl_count, dl_table_count),
        "total_events": total_count,
        "delivery_lag_seconds": float(lag_seconds),
    }

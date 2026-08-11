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
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_ATTEMPTS = 5


async def enqueue(db: AsyncSession, *, aggregate_type: str, aggregate_id: str,
                  event_type: str, payload: dict[str, Any], sensitivity: str = "normal") -> None:
    """Call inside the SAME transaction as the business write."""
    await db.execute(text("""
        INSERT INTO outbox_events
            (id, aggregate_type, aggregate_id, event_type, payload, sensitivity, status, attempts)
        VALUES (uuid_generate_v4(), :at, :aid, :et, CAST(:pl AS jsonb), :sev, 'pending', 0)
    """), {"at": aggregate_type, "aid": aggregate_id, "et": event_type,
           "pl": json.dumps(payload), "sev": sensitivity})


async def ship_pending(db: AsyncSession, cloud_send, batch: int = 100) -> int:
    """Worker step: claim → send → mark. At-least-once with idempotency key.

    `cloud_send(row) -> bool` — row dict includes 'id' which the receiver uses
    as an idempotency key to deduplicate.

    Claiming rows with status='in_flight' in a separate committed transaction
    ensures that if the process dies between send and status-update, the row
    stays 'in_flight' (not 'pending') and can be retried without duplication
    on our side. The receiver deduplicates on event id.
    """
    # Step 1: Claim pending rows — set status='in_flight' and commit
    # FOR UPDATE SKIP LOCKED prevents concurrent workers from claiming the same row.
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

    # Commit the claim so it persists even if we crash during send
    await db.commit()

    # Step 2: Send each row, then update status
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
            # Increment attempts; if exhausted, move to dead_letter
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
        # Commit each row's status update individually so partial progress is saved
        await db.commit()

    return sent


async def reap_stranded(db: AsyncSession, stale_minutes: int = 10) -> int:
    """Return in_flight rows older than `stale_minutes` back to pending.

    If a process dies between claiming a row and updating its status, the row
    stays in_flight forever. This reaper moves them back to pending so they can
    be retried. Call periodically from the background worker.
    """
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

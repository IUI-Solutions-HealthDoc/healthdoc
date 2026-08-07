"""
Durable fallback for data_access_log writes that fail.

Repo path: backend/app/consent/access_log_fallback.py

WHY THIS EXISTS
----------------
access_log.py's log_patient_data_access() must never block a clinical
read if logging fails (Tech Lead: "blocking patient care because the
logger had a bad day is worse than losing a row" — correct, and kept).
But `logger.exception()` alone is not durable: it writes to container
stdout, which is gone the moment log shipping is down or the container
restarts. That converts a recoverable incident ("we missed some access
log rows, replay them from the fallback file") into an invisible one
("we have no idea access logging was broken for three days").

WHY A LOCAL FILE, NOT THE POSTGRES OUTBOX (outbox_events, 0031)
-----------------------------------------------------------------
outbox_events is itself a Postgres table, written in the SAME
transaction as the business mutation it's shipping (§4A.3). If the
reason data_access_log's INSERT failed is "Postgres is unreachable" or
"this session's connection just died", an outbox INSERT would fail for
the identical reason — it does not survive the failure mode this exists
to survive. A local append-only file does: it only requires the local
filesystem to be writable, which is a weaker, more independent
assumption than "Postgres is reachable".

CAVEAT, STATED HONESTLY: this file only survives the *container*
outliving the failure. If the container is destroyed without a mounted
volume for this path, rows written to the fallback between the last
volume flush and container death are still lost. That's a smaller and
much rarer window than "every DB hiccup loses the row silently", which
is the problem this replaces — not a claim that this is bulletproof.
Set DATA_ACCESS_LOG_FALLBACK_PATH to a mounted volume in deployment.

RECOVERY
--------
A scheduled job (not built here — flagged as a follow-up, same as the
consent-expiry job) should periodically read this file, attempt to
insert each row into data_access_log, and truncate/rotate on success.
Until that job exists, an on-call engineer can replay it manually:
    grep at minimum gets you the JSON lines; each is one data_access_log
    row plus a `_failure_reason` field for context.

METRICS
-------
increment_fallback_counter() is a thin, swappable seam — wire it to
whatever metrics backend the repo standardizes on (not decided yet in
this codebase as far as this ticket's scope goes). Until then it logs
at CRITICAL, which most log-shipping/alerting setups already treat as
page-worthy, so failures are not silent even before real metrics wiring
lands.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

from app.common.config import get_settings

logger = logging.getLogger(__name__)

# Resolved: `data_access_log_fallback_path` now lives in Settings
# (app/common/config.py), added by the reviewer rather than sent back — Vani
# was right that config.py is outside the consent module's scope to edit.
#
# Read lazily rather than at import: a module-level get_settings() call binds
# the value at import time, so tests that monkeypatch the env see the old path
# and write to the real one.
def _fallback_log_path() -> str:
    return get_settings().data_access_log_fallback_path

# One process-wide lock: this fires rarely (only on DB failure), so
# contention is a non-issue; correctness of "never interleave two
# partial JSON lines" is what matters.
_write_lock = threading.Lock()


def increment_fallback_counter(reason: str) -> None:
    """
    Swappable metrics seam — see module docstring. Logs at CRITICAL so
    this is page-worthy under most log-shipping/alerting setups even
    before a real metrics client is wired in here.
    """
    logger.critical(
        "data_access_log fallback write triggered (reason=%s) — clinical access "
        "was NOT logged to the primary table, see fallback file at %s",
        reason,
        _fallback_log_path(),
    )


def _write_fallback_row_sync(row: dict, *, failure_reason: str) -> bool:
    """
    Synchronous body of write_fallback_row() — open()/write()/flush()/
    fsync() all block, so this must only ever run off the event loop
    (see write_fallback_row()). threading.Lock is correct here precisely
    because this now runs in a worker thread, not on the loop.
    """
    payload = {
        **row,
        "_fallback_written_at": datetime.now(timezone.utc).isoformat(),
        "_failure_reason": failure_reason,
    }
    try:
        path = _fallback_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps(payload, default=str) + "\n"
        with _write_lock:
            # Open in append mode + explicit flush/fsync: a crash right
            # after this call should not lose the line sitting in an
            # OS buffer.
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        increment_fallback_counter(failure_reason)
        return True
    except Exception:
        # Genuinely last resort — even the fallback couldn't be
        # written (disk full, permissions, path unmountable). This is
        # the one place logger.exception() alone is the right answer,
        # because there is nothing durable left to fall back to.
        logger.exception(
            "data_access_log fallback write ITSELF failed — row lost. "
            "This should page immediately: %s",
            {k: v for k, v in row.items() if k not in ("justification",)},
        )
        return False


async def write_fallback_row(row: dict, *, failure_reason: str) -> bool:
    """
    Best-effort durable write of a row that failed to reach
    data_access_log. Returns True/False for whether the fallback write
    itself succeeded — callers should NOT raise or block on False; if
    even the fallback write fails, logger.exception() upstream is the
    last resort, exactly as before this module existed.

    `row` values must already be JSON-serialisable (str/bool/None) —
    callers convert UUIDs/datetimes before calling this.

    PR #266 review: the write itself (open/write/flush/fsync) used to
    run inline on the caller's event loop. fsync can take tens of
    milliseconds, and the usual reason this path fires at all is
    Postgres being unreachable — meaning every request takes this path
    at once, so the stall lands exactly when the system is already
    degraded. asyncio.to_thread() moves the blocking work off the loop.
    """
    return await asyncio.to_thread(_write_fallback_row_sync, row, failure_reason=failure_reason)


def serialise_row_for_fallback(
    *,
    user_id: uuid.UUID | None,
    role: str | None,
    resource_type: str,
    resource_id: uuid.UUID | None,
    patient_id: uuid.UUID | None,
    purpose_code: str,
    access_channel: str,
    emergency_access: bool,
    consent_required: bool | None,
    consent_verified: bool | None,
) -> dict:
    """Shape mirrors DataAccessLog's insertable columns (minus PK/accessed_at,
    which the recovery job sets at replay time)."""
    return {
        "user_id": str(user_id) if user_id else None,
        "role": role,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id else None,
        "patient_id": str(patient_id) if patient_id else None,
        "purpose_code": purpose_code,
        "access_channel": access_channel,
        "emergency_access": emergency_access,
        "consent_required": consent_required,
        "consent_verified": consent_verified,
    }

"""Dedicated durable ABDM work; payloads contain identifiers, never clinical data.

Kept separate from the edge/cloud outbox so its generic shipper cannot consume
ABDM work. A lease is committed before dispatch; expiry makes crashes recoverable.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk

TOKEN_CALLBACK_RECOVERY_MARKER = "Operator queued one lost-token-callback recovery"


class AbdmJob(Base, UUIDPk, Timestamps):
    __tablename__ = "abdm_jobs"
    facility_id = Column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    kind = Column(String(50), nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(String(50), nullable=False, server_default="pending")
    attempts = Column(Integer, nullable=False, server_default="0")
    available_at = Column(DateTime(timezone=True), nullable=False)
    lease_token = Column(UUID(as_uuid=True), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "kind IN ('context_notify','hip_transfer','hip_notify','link_token','link_context','hiu_notify','hiu_consent','hiu_request','callback_ack','hiu_fetch')",
            name="abdm_job_kind",
        ),
        CheckConstraint("status IN ('pending','leased','done','dead')", name="abdm_job_status"),
        CheckConstraint("attempts >= 0", name="abdm_job_attempts"),
        CheckConstraint(
            "(lease_token IS NULL) = (lease_until IS NULL)", name="abdm_job_lease_pair"
        ),
        Index("ix_abdm_jobs_facility_id", "facility_id"),
        Index("ix_abdm_jobs_ready", "status", "available_at"),
    )


class AbdmCallbackReply(Base, UUIDPk, Timestamps):
    """Identifier-only reply intent, committed with the accepted business state."""

    __tablename__ = "abdm_callback_replies"
    facility_id = Column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    kind = Column(String(50), nullable=False)
    gateway_request_id = Column(String(100), nullable=False)
    payload_sha256 = Column(String(64), nullable=False)
    subject_ids = Column(JSONB, nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=True)
    # Bounded M2 response snapshots, encrypted with per-reply associated data.
    # Never OTPs, private keys or bearer credentials; erased after delivery/expiry.
    response_encrypted = Column(LargeBinary, nullable=True)
    response_expires_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint(
            "kind IN ('hip_consent','hip_request','hiu_consent','hip_link_confirm','hip_discover','hip_link_init','hip_link_reject','hip_profile')",
            name="abdm_callback_reply_kind",
        ),
        Index("ix_abdm_callback_replies_facility_id", "facility_id"),
    )


def job_id(kind: str, target_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"healthdoc:abdm-job:{kind}:{target_id}")


async def enqueue(
    db: AsyncSession, *, kind: str, target_id: uuid.UUID, facility_id: uuid.UUID
) -> uuid.UUID:
    """Same transaction as the business row. Replays do not reset completed work."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    ident = job_id(kind, target_id)
    await db.execute(
        insert(AbdmJob)
        .values(
            id=ident,
            facility_id=facility_id,
            kind=kind,
            target_id=target_id,
            available_at=datetime.now(UTC),
            status="pending",
            attempts=0,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    return ident


async def claim(
    db: AsyncSession, *, now: datetime | None = None, ident: uuid.UUID | None = None
) -> AbdmJob | None:
    now = now or datetime.now(UTC)
    ready = or_(
        (AbdmJob.status == "pending") & (AbdmJob.available_at <= now),
        (AbdmJob.status == "leased") & (AbdmJob.lease_until <= now),
    )
    if ident is not None:
        ready = ready & (AbdmJob.id == ident)
    row = (
        await db.execute(
            select(AbdmJob)
            .where(ready)
            .order_by(AbdmJob.available_at, AbdmJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    # A token request whose worker crashed may already have reached NHA.
    # Do not automatically generate again: NHA limits generation per address.
    attempt_limit = 5
    if row.kind == "link_token":
        attempt_limit = 2 if row.last_error == TOKEN_CALLBACK_RECOVERY_MARKER else 1
    if row.attempts >= attempt_limit:
        row.status = "dead"
        row.last_error = "Worker retry limit reached"
        row.lease_token = row.lease_until = None
        await db.commit()
        return None
    row.status = "leased"
    row.lease_token = uuid.uuid4()
    row.lease_until = now + timedelta(minutes=2)
    row.attempts += 1
    await db.commit()
    return row


async def finish(
    db: AsyncSession,
    job: AbdmJob,
    *,
    error: str | None = None,
    deferred: bool = False,
    terminal: bool = False,
) -> bool:
    # A stale worker must not overwrite a lease that a replacement owns.
    values = dict(status="done", lease_token=None, lease_until=None, last_error=None)
    if error is not None:
        values.update(
            status="pending" if deferred or job.attempts < 5 else "dead",
            last_error=error[:100],
            available_at=datetime.now(UTC)
            + timedelta(seconds=60 if deferred else min(900, 2**job.attempts * 10)),
        )
        if deferred:
            values["attempts"] = max(0, job.attempts - 1)
        # A pre-dispatch deferral sends nothing. Actual token-request failures
        # need inspection, not an automatic five-attempt generation loop.
        if terminal or (job.kind == "link_token" and not deferred):
            values["status"] = "dead"
    result = await db.execute(
        update(AbdmJob)
        .where(
            AbdmJob.id == job.id,
            AbdmJob.status == "leased",
            AbdmJob.lease_token == job.lease_token,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return result.rowcount == 1


async def renew(db: AsyncSession, ident: uuid.UUID, token: uuid.UUID) -> bool:
    result = await db.execute(
        update(AbdmJob)
        .where(
            AbdmJob.id == ident,
            AbdmJob.status == "leased",
            AbdmJob.lease_token == token,
        )
        .values(lease_until=datetime.now(UTC) + timedelta(minutes=2))
    )
    await db.commit()
    return result.rowcount == 1

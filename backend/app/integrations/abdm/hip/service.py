"""HIP (M2) behaviour: link care contexts, honour consent, hand over data.

THE ONE FUNCTION THAT MATTERS
-----------------------------
`authorise_hi_request()` is the gate. Everything else in this module moves
bookkeeping around; that function decides whether a patient's records leave the
building. It is written as a sequence of explicit refusals with a named reason
each, rather than a boolean expression, because "why was this refused" is a
question an assessor asks and a compound `and` cannot answer.

It fails CLOSED at every step. An artefact we do not hold, an artefact that is
revoked, a window that does not cover what was asked for, an HI type outside
the grant — each returns a refusal, and none of them fall through to a partial
release. There is no branch in this module that releases data without a stored,
unexpired, matching artefact.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.abdm import hi_crypto
from app.integrations.abdm.hip.models import (
    AbdmCareContext,
    AbdmCareContextLink,
    AbdmHipConsentArtefact,
    AbdmHipHealthInformationRequest,
)

log = logging.getLogger("healthdoc.abdm.hip")


class HipError(Exception):
    """A refusal with a code the caller may safely surface."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Authorisation:
    """The answer to 'may this request have data, and which data'."""

    artefact: AbdmHipConsentArtefact
    hi_types: list[str]
    date_range_from: datetime | None
    date_range_to: datetime | None


def _aware(value: datetime | None) -> datetime | None:
    """Postgres hands back aware datetimes; a naive one is a bug upstream.

    Comparing a naive to an aware datetime raises TypeError, which would
    surface as a 500 on a consent check — the worst possible place for an
    ambiguous timestamp. Normalising here makes the failure impossible rather
    than rare.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def authorise_hi_request(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    consent_artefact_id: str,
    requested_hi_types: list[str],
    requested_from: datetime | None,
    requested_to: datetime | None,
    now: datetime | None = None,
) -> Authorisation:
    """Decide whether a health-information request may be served.

    Raises HipError on every refusal path. Returns the narrowed grant on
    success — narrowed, not echoed: what the requester asked for is a proposal,
    and what the artefact permits is the answer.
    """
    now = now or datetime.now(UTC)

    artefact = (
        await db.execute(
            select(AbdmHipConsentArtefact).where(
                AbdmHipConsentArtefact.consent_artefact_id == consent_artefact_id,
                # Facility-scoped like every other read in this codebase. An
                # artefact notified to one facility is not authority for
                # another facility's records, even inside one deployment.
                AbdmHipConsentArtefact.facility_id == facility_id,
            )
        )
    ).scalar_one_or_none()

    if artefact is None:
        # Deliberately the same shape of refusal as a revoked artefact. Telling
        # a caller "that consent exists but is revoked" versus "no such
        # consent" distinguishes real artefact ids from invented ones, which is
        # an enumeration oracle over other people's consents.
        raise HipError("consent_not_valid", "No usable consent artefact for this request")

    if artefact.status != "granted":
        raise HipError("consent_not_valid", "No usable consent artefact for this request")

    expires_at = _aware(artefact.expires_at)
    if expires_at is not None and expires_at <= now:
        raise HipError("consent_expired", "The consent artefact has expired")

    granted_types = set(artefact.hi_types or [])
    asked_types = set(requested_hi_types or [])
    if not asked_types:
        raise HipError("hi_type_not_permitted", "No health-information type was requested")
    outside = asked_types - granted_types
    if outside:
        # The names of the types they asked for are their own words, so echoing
        # them back leaks nothing.
        raise HipError(
            "hi_type_not_permitted",
            f"Consent does not cover: {', '.join(sorted(outside))}",
        )

    grant_from = _aware(artefact.date_range_from)
    grant_to = _aware(artefact.date_range_to)
    req_from = _aware(requested_from)
    req_to = _aware(requested_to)

    # A request that reaches outside the granted window is refused, not
    # silently clipped. Clipping would hand back a shorter history than was
    # asked for with no indication it had been trimmed, and the HIU would
    # record that as the patient's complete record for that period.
    if grant_from is not None and req_from is not None and req_from < grant_from:
        raise HipError("date_range_not_permitted", "Requested period starts before the consent window")
    if grant_to is not None and req_to is not None and req_to > grant_to:
        raise HipError("date_range_not_permitted", "Requested period ends after the consent window")

    return Authorisation(
        artefact=artefact,
        hi_types=sorted(asked_types),
        date_range_from=req_from or grant_from,
        date_range_to=req_to or grant_to,
    )


async def record_consent_notification(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    artefact_id: str,
    abha_address: str,
    status: str,
    hi_types: list[str],
    date_range_from: datetime | None,
    date_range_to: datetime | None,
    expires_at: datetime | None,
    raw: dict,
) -> AbdmHipConsentArtefact:
    """Store, or update, what the consent manager told us.

    A revocation for an artefact we never saw still creates a row. That looks
    redundant and is not: it is the difference between "we were told to stop
    and did" and "we have no record of being told", which is exactly the
    question asked after a complaint.
    """
    if status not in ("granted", "revoked", "expired"):
        raise HipError("unknown_status", f"Unrecognised consent status {status!r}")

    existing = (
        await db.execute(
            select(AbdmHipConsentArtefact).where(
                AbdmHipConsentArtefact.consent_artefact_id == artefact_id
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        # Revocation is terminal. A later 'granted' for the same artefact id is
        # not a reinstatement — ABDM issues a NEW artefact for that — so
        # accepting one would let a replayed notification undo a revocation.
        if existing.status == "revoked" and status == "granted":
            raise HipError("consent_revoked", "A revoked artefact cannot be re-granted")
        existing.status = status
        existing.raw_artefact = raw
        if expires_at is not None:
            existing.expires_at = expires_at
        return existing

    artefact = AbdmHipConsentArtefact(
        facility_id=facility_id,
        consent_artefact_id=artefact_id,
        abha_address=abha_address,
        status=status,
        hi_types=hi_types,
        date_range_from=date_range_from,
        date_range_to=date_range_to,
        expires_at=expires_at,
        raw_artefact=raw,
    )
    db.add(artefact)
    await db.flush()
    return artefact


async def list_care_contexts_for_transfer(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    abha_address: str,
    authorisation: Authorisation,
) -> list[AbdmCareContext]:
    """The care contexts this authorisation actually reaches.

    Joined through a CONFIRMED link, not through the artefact alone. A consent
    artefact says the patient agreed; a confirmed link says these particular
    records at this particular facility are theirs. Releasing on the artefact
    alone would hand over another patient's contexts to anyone who obtained a
    valid artefact id.
    """
    stmt = (
        select(AbdmCareContext)
        .join(AbdmCareContextLink, AbdmCareContextLink.patient_id == AbdmCareContext.patient_id)
        .where(
            AbdmCareContext.facility_id == facility_id,
            AbdmCareContextLink.facility_id == facility_id,
            AbdmCareContextLink.abha_address == abha_address,
            AbdmCareContextLink.status == "confirmed",
            AbdmCareContext.hi_type.in_(authorisation.hi_types),
        )
    )
    return list((await db.execute(stmt)).scalars().unique().all())


def encrypt_bundle_for_hiu(
    bundle: dict,
    *,
    hiu_public_key_b64: str,
    hiu_nonce_b64: str,
) -> tuple[str, dict, str]:
    """Encrypt one FHIR bundle for the requesting HIU.

    Returns (ciphertext_b64, our_key_material_wire, sha256_of_plaintext).

    A fresh keypair PER BUNDLE. Reusing one across a transfer would mean a
    single compromised ephemeral key opens every record in it, and the cost of
    generating another is a few microseconds.
    """
    plaintext = json.dumps(bundle, separators=(",", ":"), sort_keys=True)
    ours = hi_crypto.generate_key_material()
    aes_key, iv = hi_crypto.derive_shared_key(
        private_key=ours.private_key,
        peer_public_key_b64=hiu_public_key_b64,
        our_nonce_b64=ours.nonce_b64,
        peer_nonce_b64=hiu_nonce_b64,
    )
    ciphertext = hi_crypto.encrypt(plaintext, aes_key=aes_key, iv=iv)
    digest = hashlib.sha256(plaintext.encode()).hexdigest()
    # `ours.private_key` goes out of scope here and is never returned, stored
    # or logged. The HIP side of the exchange is genuinely ephemeral.
    return ciphertext, ours.to_wire(), digest


async def record_hi_request(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    transaction_id: str,
    consent_artefact_id: str,
    hiu_key_material: dict,
    data_push_url: str,
    gateway_request_id: str | None,
) -> AbdmHipHealthInformationRequest:
    """Durable record that a request arrived, written before any data moves."""
    # Explicit id, for the same reason hiu/service.py gives: the caller updates
    # this row again in the same flush (status, bundles_sent), and a row whose
    # id came from the column's server default cannot be updated afterwards
    # under the SQLite test fixture — it stores the generated id as a string
    # while the ORM holds a UUID, so the UPDATE matches nothing. Postgres is
    # unaffected either way; choosing the id here makes the path testable.
    row = AbdmHipHealthInformationRequest(
        id=uuid.uuid4(),
        facility_id=facility_id,
        transaction_id=transaction_id,
        consent_artefact_id=consent_artefact_id,
        hiu_key_material=hiu_key_material,
        data_push_url=data_push_url,
        gateway_request_id=gateway_request_id,
        status="received",
    )
    db.add(row)
    await db.flush()
    return row

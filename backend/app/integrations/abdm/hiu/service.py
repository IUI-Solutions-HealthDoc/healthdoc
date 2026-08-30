"""HIU (M3) behaviour: ask for consent, hold the artefact, open what arrives.

THE KEY LIFECYCLE IS THE INTERESTING PART
-----------------------------------------
Everything else here is a state machine over rows. The part worth reviewing is
what happens to the ephemeral private key between `begin_hi_request()` and
`receive_bundle()`:

    begin_hi_request   generate keypair -> send public half -> store private
                       half encrypted, bound to this row, with an expiry
    receive_bundle     decrypt with it, verify, store the fact
    complete_request   clear it

The key is encrypted with `encrypt_pii`'s associated_data bound to the request
id. That is not ceremony: without binding, a private-key blob lifted from one
request row and pasted into another decrypts cleanly, because GCM authenticates
bytes and not which row they came from. Bound, the paste fails.

`key_expires_at` exists so an abandoned request cannot leave a usable private
key in the database indefinitely. A transfer that arrives after it is refused
rather than opened — late data is a failed transfer to retry, not a reason to
keep key material alive forever.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.security import current_aes_key_version, decrypt_pii, encrypt_pii
from app.integrations.abdm import hi_crypto
from app.integrations.abdm.hiu.models import (
    AbdmConsentRequest,
    AbdmHiuConsentArtefact,
    AbdmHiuHealthInformationRequest,
    AbdmReceivedBundle,
)

log = logging.getLogger("healthdoc.abdm.hiu")

#: How long a published public key stays openable. Long enough for a HIP to
#: assemble a real record set, short enough that an abandoned request stops
#: being a live key. Not a setting yet — make it one when a real sandbox
#: transfer shows what the gateway actually takes.
KEY_LIFETIME = timedelta(hours=12)

_VALID_PURPOSES = {"CAREMGT", "BTG", "PUBHLTH", "HPAYMT", "DSRCH", "PATRQT"}


class HiuError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _aad(request_id: uuid.UUID) -> bytes:
    """Binds a private-key blob to the one row entitled to it."""
    return f"abdm-hiu-hi-request:{request_id}".encode()


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def create_consent_request(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    patient_id: uuid.UUID | None,
    abha_address: str,
    purpose_code: str,
    hi_types: list[str],
    date_range_from: datetime,
    date_range_to: datetime,
    requested_expiry: datetime,
    created_by: uuid.UUID,
) -> AbdmConsentRequest:
    """Record the ask. The gateway call is the caller's next step.

    Written before the gateway is contacted, deliberately: if the call fails we
    still hold evidence that this facility asked for this person's records,
    which is the thing a patient complaint is about.
    """
    if purpose_code not in _VALID_PURPOSES:
        # An unrecognised purpose is refused rather than passed through. ABDM
        # rejects it anyway, but a local refusal keeps an unexplainable purpose
        # code out of our own consent history.
        raise HiuError("invalid_purpose", f"Unknown ABDM purpose code {purpose_code!r}")
    if not hi_types:
        raise HiuError("no_hi_types", "At least one health-information type is required")
    if date_range_to < date_range_from:
        raise HiuError("invalid_range", "The requested period ends before it starts")

    row = AbdmConsentRequest(
        facility_id=facility_id,
        patient_id=patient_id,
        abha_address=abha_address,
        purpose_code=purpose_code,
        hi_types=hi_types,
        date_range_from=date_range_from,
        date_range_to=date_range_to,
        requested_expiry=requested_expiry,
        status="requested",
        created_by=created_by,
    )
    db.add(row)
    await db.flush()
    return row


async def record_artefact(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    consent_request: AbdmConsentRequest,
    artefact_id: str,
    status: str,
    hi_types: list[str],
    date_range_from: datetime | None,
    date_range_to: datetime | None,
    expires_at: datetime | None,
    raw: dict,
) -> AbdmHiuConsentArtefact:
    """Store a granted or revoked artefact against the request that asked."""
    if status not in ("granted", "revoked", "expired"):
        raise HiuError("unknown_status", f"Unrecognised artefact status {status!r}")

    existing = (
        await db.execute(
            select(AbdmHiuConsentArtefact).where(
                AbdmHiuConsentArtefact.consent_artefact_id == artefact_id
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.status == "revoked" and status == "granted":
            raise HiuError("consent_revoked", "A revoked artefact cannot be re-granted")
        existing.status = status
        existing.raw_artefact = raw
        if status != "granted":
            # A revoked artefact must stop authorising in-flight requests too,
            # not merely future ones.
            await _expire_open_requests(db, artefact_row_id=existing.id)
        return existing

    artefact = AbdmHiuConsentArtefact(
        facility_id=facility_id,
        consent_request_id=consent_request.id,
        consent_artefact_id=artefact_id,
        status=status,
        hi_types=hi_types,
        date_range_from=date_range_from,
        date_range_to=date_range_to,
        expires_at=expires_at,
        raw_artefact=raw,
    )
    db.add(artefact)
    consent_request.status = "granted" if status == "granted" else "revoked"
    await db.flush()
    return artefact


async def _expire_open_requests(db: AsyncSession, *, artefact_row_id: uuid.UUID) -> None:
    rows = (
        await db.execute(
            select(AbdmHiuHealthInformationRequest).where(
                AbdmHiuHealthInformationRequest.artefact_id == artefact_row_id,
                AbdmHiuHealthInformationRequest.status.in_(("requested", "acknowledged")),
            )
        )
    ).scalars().all()
    for row in rows:
        row.status = "expired"
        row.failure_reason = "Consent artefact was revoked while this request was open"
        _clear_key(row)


def _clear_key(row: AbdmHiuHealthInformationRequest) -> None:
    """Drop key material. Both columns together — the CHECK requires it."""
    row.private_key_encrypted = None
    row.key_version = None


async def begin_hi_request(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    artefact: AbdmHiuConsentArtefact,
    created_by: uuid.UUID,
    now: datetime | None = None,
) -> tuple[AbdmHiuHealthInformationRequest, dict]:
    """Mint key material for a data request and persist the private half safely.

    Returns the row and the key-material block to send to the gateway. The
    private key is in the row (encrypted), never in the returned block —
    `to_wire()` is what guarantees that and it is tested.
    """
    now = now or datetime.now(UTC)

    if artefact.status != "granted":
        raise HiuError("consent_not_valid", "The consent artefact is not in a granted state")
    expires_at = _aware(artefact.expires_at)
    if expires_at is not None and expires_at <= now:
        raise HiuError("consent_expired", "The consent artefact has expired")

    material = hi_crypto.generate_key_material()

    # The id is assigned here rather than left to the column's server default,
    # because the private key is bound to it: the blob has to be encrypted
    # against an id that already exists, and the row has to be written with the
    # blob already in it. Insert-then-update would need the id to come back
    # from the database first — one more round trip and one more failure mode,
    # and a failure mode the SQLite test fixture actually hits, so that shape
    # would be untestable as well as slower.
    request_id = uuid.uuid4()
    version = current_aes_key_version()

    row = AbdmHiuHealthInformationRequest(
        id=request_id,
        facility_id=facility_id,
        artefact_id=artefact.id,
        status="requested",
        public_key_b64=material.public_key_b64,
        nonce_b64=material.nonce_b64,
        key_expires_at=now + KEY_LIFETIME,
        created_by=created_by,
        private_key_encrypted=encrypt_pii(
            material.private_key.private_bytes_raw().hex(),
            key_version=version,
            associated_data=_aad(request_id),
        ),
        # Stored alongside the blob (which already embeds it) so a rotation
        # report can find in-flight requests without decrypting every one.
        key_version=version,
    )
    db.add(row)
    await db.flush()

    return row, material.to_wire()


def _load_private_key(row: AbdmHiuHealthInformationRequest):
    if row.private_key_encrypted is None:
        raise HiuError("key_unavailable", "This request no longer holds key material")
    hex_key = decrypt_pii(row.private_key_encrypted, associated_data=_aad(row.id))
    return hi_crypto.X25519PrivateKey.from_private_bytes(bytes.fromhex(hex_key))


async def receive_bundle(
    db: AsyncSession,
    *,
    request: AbdmHiuHealthInformationRequest,
    ciphertext_b64: str,
    hip_public_key_b64: str,
    hip_nonce_b64: str,
    care_context_reference: str | None,
    now: datetime | None = None,
) -> tuple[AbdmReceivedBundle, str]:
    """Decrypt one pushed bundle and record that it arrived.

    Returns the receipt row and the decrypted document, which the caller ships
    through the outbox. The plaintext is deliberately NOT persisted here — the
    receipt carries a sha256 so a later reader can prove which document this
    row describes without this table holding clinical content.
    """
    now = now or datetime.now(UTC)

    if _aware(request.key_expires_at) <= now:
        request.status = "expired"
        _clear_key(request)
        raise HiuError("key_expired", "Key material for this request has expired")

    private_key = _load_private_key(request)
    aes_key, iv = hi_crypto.derive_shared_key(
        private_key=private_key,
        peer_public_key_b64=hip_public_key_b64,
        our_nonce_b64=request.nonce_b64,
        peer_nonce_b64=hip_nonce_b64,
    )

    try:
        plaintext = hi_crypto.decrypt(ciphertext_b64, aes_key=aes_key, iv=iv)
    except hi_crypto.HiCryptoError as exc:
        # Recorded, not swallowed. A bundle that failed to authenticate is a
        # security event: either the wrong key or a tampered payload. Treating
        # it as "no data" would let tampering read as an empty record.
        receipt = AbdmReceivedBundle(
            facility_id=request.facility_id,
            hi_request_id=request.id,
            care_context_reference=care_context_reference,
            content_sha256="",
            status="undecipherable",
            failure_reason=str(exc),
        )
        db.add(receipt)
        request.status = "partial"
        await db.flush()
        raise HiuError("undecipherable", "A pushed bundle failed authentication") from exc

    receipt = AbdmReceivedBundle(
        facility_id=request.facility_id,
        hi_request_id=request.id,
        care_context_reference=care_context_reference,
        content_sha256=hashlib.sha256(plaintext.encode()).hexdigest(),
        status="stored",
    )
    db.add(receipt)
    request.status = "received"
    await db.flush()
    return receipt, plaintext


async def complete_request(
    db: AsyncSession, *, request: AbdmHiuHealthInformationRequest
) -> None:
    """Finish a transfer and drop the key that could still open it."""
    _clear_key(request)
    await db.flush()

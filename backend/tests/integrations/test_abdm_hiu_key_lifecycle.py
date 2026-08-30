"""HIU key handling: the private key is encrypted, bound, and cleared.

This is the other half of what a WASA assessor means by "HIP/HIU key handling".
The HIU is the only party that has to persist a private key — the exchange is
asynchronous — so these tests pin the three properties that make that
acceptable: it is never stored in plaintext, a blob cannot be moved between
rows, and it stops existing when it can no longer open anything.

The end-to-end test at the bottom encrypts as a HIP would and decrypts through
the HIU service, which is the closest thing to a real transfer that can be run
without a sandbox. It proves our two halves agree. It does not prove ABDM
agrees, and nothing here should be read as claiming that.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy import text

from app.common.security import decrypt_pii
from app.integrations.abdm import hi_crypto
from app.integrations.abdm.hip import service as hip_service
from app.integrations.abdm.hiu import service
from app.integrations.abdm.hiu.models import (
    AbdmConsentRequest,
    AbdmHiuConsentArtefact,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
FACILITY = uuid.uuid4()
ACTOR = uuid.uuid4()


@pytest.fixture
async def hiu_db(db):
    await db.execute(
        text(
            "INSERT INTO facilities (id, code, name, state_code, timezone, is_active) "
            "VALUES (:id, 'HIUF1', 'Test', 'DL', 'Asia/Kolkata', 1)"
        ),
        {"id": str(FACILITY)},
    )
    return db


async def _granted_artefact(db, *, status="granted", expires=None):
    request = AbdmConsentRequest(
        id=uuid.uuid4(),
        facility_id=FACILITY, patient_id=None, abha_address="someone@sbx",
        purpose_code="CAREMGT", hi_types=["OPConsultation"],
        date_range_from=NOW - timedelta(days=30), date_range_to=NOW,
        requested_expiry=NOW + timedelta(days=30), status="requested",
        created_by=ACTOR,
    )
    db.add(request)
    await db.flush()

    # Explicit ids throughout. The shared SQLite fixture registers its own
    # uuid_generate_v4() returning a STRING, so a row that takes its id from
    # the column's server default is stored under a string key while the ORM
    # holds a UUID — and any later UPDATE matches zero rows. That is a fixture
    # limitation, not a production one (Postgres returns a real uuid), but it
    # makes insert-then-update untestable unless the id is supplied here.
    artefact = AbdmHiuConsentArtefact(
        id=uuid.uuid4(),
        facility_id=FACILITY, consent_request_id=request.id,
        consent_artefact_id=f"ART-{uuid.uuid4().hex[:8]}", status=status,
        hi_types=["OPConsultation"],
        date_range_from=NOW - timedelta(days=30), date_range_to=NOW,
        expires_at=expires if expires is not None else NOW + timedelta(days=30),
        raw_artefact={},
    )
    db.add(artefact)
    await db.flush()
    return artefact


async def test_the_private_key_is_never_stored_in_plaintext(hiu_db):
    artefact = await _granted_artefact(hiu_db)
    row, wire = await service.begin_hi_request(
        hiu_db, facility_id=FACILITY, artefact=artefact, created_by=ACTOR, now=NOW,
    )

    assert row.private_key_encrypted is not None
    stored = bytes(row.private_key_encrypted)

    # The ciphertext must not contain the key, in raw or hex form.
    opened = decrypt_pii(stored, associated_data=f"abdm-hiu-hi-request:{row.id}".encode())
    assert bytes.fromhex(opened) not in stored
    assert opened.encode() not in stored
    # And the wire block the gateway receives must not carry it at all.
    assert opened not in json.dumps(wire)


async def test_the_key_version_is_recorded_beside_the_blob(hiu_db):
    """So a rotation report can find in-flight requests without decrypting
    every one of them. The CHECK requires the two to travel together."""
    artefact = await _granted_artefact(hiu_db)
    row, _ = await service.begin_hi_request(
        hiu_db, facility_id=FACILITY, artefact=artefact, created_by=ACTOR, now=NOW,
    )
    assert row.key_version is not None


async def test_a_key_blob_cannot_be_moved_to_another_request(hiu_db):
    """GCM authenticates bytes, not which row they came from. Without the
    associated-data binding, a blob lifted from one row opens in another."""
    artefact = await _granted_artefact(hiu_db)
    first, _ = await service.begin_hi_request(
        hiu_db, facility_id=FACILITY, artefact=artefact, created_by=ACTOR, now=NOW,
    )
    second, _ = await service.begin_hi_request(
        hiu_db, facility_id=FACILITY, artefact=artefact, created_by=ACTOR, now=NOW,
    )

    # InvalidTag specifically, not Exception: the point is that GCM's
    # authentication rejects it, and a bare Exception would also pass if the
    # call failed for some unrelated reason.
    with pytest.raises(InvalidTag):
        decrypt_pii(
            bytes(first.private_key_encrypted),
            associated_data=f"abdm-hiu-hi-request:{second.id}".encode(),
        )


async def test_a_request_under_a_revoked_artefact_is_refused(hiu_db):
    artefact = await _granted_artefact(hiu_db, status="revoked")
    with pytest.raises(service.HiuError) as caught:
        await service.begin_hi_request(
            hiu_db, facility_id=FACILITY, artefact=artefact, created_by=ACTOR, now=NOW,
        )
    assert caught.value.code == "consent_not_valid"


async def test_a_request_under_an_expired_artefact_is_refused(hiu_db):
    artefact = await _granted_artefact(hiu_db, expires=NOW - timedelta(seconds=1))
    with pytest.raises(service.HiuError) as caught:
        await service.begin_hi_request(
            hiu_db, facility_id=FACILITY, artefact=artefact, created_by=ACTOR, now=NOW,
        )
    assert caught.value.code == "consent_expired"


async def test_completing_a_transfer_destroys_the_key(hiu_db):
    """A key that can no longer open anything should not still be in a row."""
    artefact = await _granted_artefact(hiu_db)
    row, _ = await service.begin_hi_request(
        hiu_db, facility_id=FACILITY, artefact=artefact, created_by=ACTOR, now=NOW,
    )
    assert row.private_key_encrypted is not None

    await service.complete_request(hiu_db, request=row)

    assert row.private_key_encrypted is None
    # Paired, because the CHECK constraint requires it and because "which key
    # opened this" must not become unanswerable.
    assert row.key_version is None


async def test_revoking_the_artefact_kills_open_requests_and_their_keys(hiu_db):
    """A revocation has to reach requests already in flight, not just future
    ones — otherwise revoking consent leaves a live key that still opens data."""
    artefact = await _granted_artefact(hiu_db)
    row, _ = await service.begin_hi_request(
        hiu_db, facility_id=FACILITY, artefact=artefact, created_by=ACTOR, now=NOW,
    )
    request = (await hiu_db.get(AbdmConsentRequest, artefact.consent_request_id))

    await service.record_artefact(
        hiu_db, facility_id=FACILITY, consent_request=request,
        artefact_id=artefact.consent_artefact_id, status="revoked",
        hi_types=["OPConsultation"], date_range_from=None, date_range_to=None,
        expires_at=None, raw={},
    )

    assert row.status == "expired"
    assert row.private_key_encrypted is None and row.key_version is None


async def test_a_transfer_arriving_after_the_key_expires_is_refused(hiu_db):
    artefact = await _granted_artefact(hiu_db)
    row, _ = await service.begin_hi_request(
        hiu_db, facility_id=FACILITY, artefact=artefact, created_by=ACTOR, now=NOW,
    )
    hip = hi_crypto.generate_key_material()

    with pytest.raises(service.HiuError) as caught:
        await service.receive_bundle(
            hiu_db, request=row, ciphertext_b64="irrelevant",
            hip_public_key_b64=hip.public_key_b64, hip_nonce_b64=hip.nonce_b64,
            care_context_reference=None,
            now=NOW + service.KEY_LIFETIME + timedelta(seconds=1),
        )
    assert caught.value.code == "key_expired"
    assert row.private_key_encrypted is None


async def test_a_bundle_encrypted_as_a_hip_would_opens_through_the_hiu_service(hiu_db):
    """The closest thing to a real transfer available without a sandbox: the
    HIP path encrypts, the HIU path decrypts, and the receipt records the
    sha256 of what arrived without storing the clinical content."""
    artefact = await _granted_artefact(hiu_db)
    row, wire = await service.begin_hi_request(
        hiu_db, facility_id=FACILITY, artefact=artefact, created_by=ACTOR, now=NOW,
    )

    bundle = {"resourceType": "Bundle", "id": "b1", "entry": [{"note": "clinical"}]}
    ciphertext, hip_wire, digest = hip_service.encrypt_bundle_for_hiu(
        bundle,
        hiu_public_key_b64=wire["dhPublicKey"]["keyValue"],
        hiu_nonce_b64=wire["nonce"],
    )

    receipt, plaintext = await service.receive_bundle(
        hiu_db, request=row, ciphertext_b64=ciphertext,
        hip_public_key_b64=hip_wire["dhPublicKey"]["keyValue"],
        hip_nonce_b64=hip_wire["nonce"],
        care_context_reference="visit-1", now=NOW,
    )

    assert json.loads(plaintext) == bundle
    assert receipt.status == "stored"
    assert receipt.content_sha256 == digest
    assert row.status == "received"


async def test_a_tampered_bundle_is_recorded_as_undecipherable_not_as_no_data(hiu_db):
    """Treating a failed authentication as an empty record is how tampering
    reads as 'the patient has no history'."""
    artefact = await _granted_artefact(hiu_db)
    row, wire = await service.begin_hi_request(
        hiu_db, facility_id=FACILITY, artefact=artefact, created_by=ACTOR, now=NOW,
    )
    hip = hi_crypto.generate_key_material()

    with pytest.raises(service.HiuError) as caught:
        await service.receive_bundle(
            hiu_db, request=row,
            ciphertext_b64="aGVsbG8gdGhlcmUgdGhpcyBpcyBub3QgYSB2YWxpZCBnY20gYmxvYg==",
            hip_public_key_b64=hip.public_key_b64, hip_nonce_b64=hip.nonce_b64,
            care_context_reference=None, now=NOW,
        )

    assert caught.value.code == "undecipherable"
    assert row.status == "partial"


@pytest.mark.parametrize("purpose", ["NOT-A-PURPOSE", "", "careMgt"])
async def test_an_unrecognised_purpose_code_is_refused(hiu_db, purpose):
    """ABDM would reject it anyway; refusing locally keeps an unexplainable
    purpose out of our own consent history."""
    with pytest.raises(service.HiuError) as caught:
        await service.create_consent_request(
            hiu_db, facility_id=FACILITY, patient_id=None,
            abha_address="someone@sbx", purpose_code=purpose,
            hi_types=["OPConsultation"], date_range_from=NOW - timedelta(days=1),
            date_range_to=NOW, requested_expiry=NOW + timedelta(days=30),
            created_by=ACTOR,
        )
    assert caught.value.code == "invalid_purpose"


async def test_a_backwards_period_is_refused(hiu_db):
    with pytest.raises(service.HiuError) as caught:
        await service.create_consent_request(
            hiu_db, facility_id=FACILITY, patient_id=None,
            abha_address="someone@sbx", purpose_code="CAREMGT",
            hi_types=["OPConsultation"], date_range_from=NOW,
            date_range_to=NOW - timedelta(days=1),
            requested_expiry=NOW + timedelta(days=30), created_by=ACTOR,
        )
    assert caught.value.code == "invalid_range"

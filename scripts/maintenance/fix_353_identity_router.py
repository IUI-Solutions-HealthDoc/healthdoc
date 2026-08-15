#!/usr/bin/env python3
"""Reconcile #353's ABHA endpoints onto the merged M2 implementation.

Run from the repo root on feat/b2-emergency-thid-v2, AFTER merging staging.
Idempotent.

THE PROBLEM
-----------
#310 merged with `link_abha` at POST /abdm/abha/link: verifies with the ABDM
gateway, stores the linking token encrypted with a key version, and marks
identity_unverified when the gateway is unreachable. That encrypted token IS
ABDM milestone M2.

#353 independently wrote a different `link_abha` in the same file at
POST /abdm/abha/patients/{id}/abha, with no gateway call and no token storage,
plus `get_abha` and `unlink_abha`. Merging it would replace the M2
implementation and regress the milestone.

Both have something the other lacks. This keeps #310's endpoint as the single
linking path and adds #353's genuinely missing pieces to it:

  * duplicate-ABHA-across-patients check (409) — #310 relies only on the
    UNIQUE constraint, which surfaces as a 500
  * already-linked-to-a-different-number guard (409)
  * GET  /patients/{id}/abha  — read
  * DELETE /patients/{id}/abha — unlink

ONE CORRECTION TO #353'S UNLINK
-------------------------------
#353's unlink clears only abha_number. That leaves
abha_linking_token_encrypted and abha_linking_key_version populated — an
encrypted ABDM token belonging to a link that no longer exists, which is both
a data-protection problem and the exact both-or-neither state 0030's CHECK
constraint was added to prevent. Unlink clears all three and audits.
"""
import pathlib
import sys

ROUTER = pathlib.Path("backend/app/integrations/abdm/identity/router.py")
if not ROUTER.exists():
    sys.exit("run me from the repo root")

text = ROUTER.read_text()

if "async def unlink_abha" in text and "_get_patient_or_404" in text:
    print("~ already reconciled")
    sys.exit(0)

if "_verify_with_gateway" not in text:
    sys.exit(
        "! this file has no _verify_with_gateway — you are on #353's version, not the\n"
        "  merged one. Merge origin/staging first and take STAGING's copy of this file,\n"
        "  then re-run:  git checkout --theirs backend/app/integrations/abdm/identity/router.py"
    )

# ------------------------------------------------------------------ imports
OLD_IMPORTS = """from app.auth.deps import AuthUser, get_current_user, require_roles
from app.common.config import get_settings
from app.common.db import get_db
from app.common.security import encrypt_pii
from app.outbox.service import enqueue"""
NEW_IMPORTS = """import uuid

from sqlalchemy import select

from app.auth.deps import AuthUser, CurrentDbUser, get_current_user, require_roles
from app.common.config import get_settings
from app.common.db import get_db
from app.common.security import encrypt_pii
from app.outbox.service import enqueue
from app.patients.models import Patient"""

if OLD_IMPORTS in text:
    text = text.replace(OLD_IMPORTS, NEW_IMPORTS, 1)
    print("+ imports")
else:
    print("! import block not as expected — add uuid/select/Patient/CurrentDbUser by hand")

# ------------------------------------------------------- helper + read model
HELPERS = '''

class AbhaOut(BaseModel):
    patient_id: uuid.UUID
    abha_number: str | None

    model_config = {"from_attributes": True}


def _normalise_abha(raw: str) -> str:
    """ABHA numbers are quoted with or without hyphens; store one form."""
    return raw.replace("-", "").strip()


async def _get_patient_or_404(
    db: AsyncSession, patient_id: uuid.UUID, facility_id: uuid.UUID
) -> Patient:
    """404 rather than 403 for another facility's patient — a 403 confirms the
    row exists, which is enough to probe for patients across facilities."""
    patient = await db.get(Patient, patient_id)
    if patient is None or patient.facility_id != facility_id:
        raise HTTPException(404, {"code": "patient_not_found"})
    return patient

'''

ANCHOR = "\n@router.post(\"/link\""
if "def _get_patient_or_404" not in text and ANCHOR in text:
    text = text.replace(ANCHOR, HELPERS + ANCHOR, 1)
    print("+ AbhaOut, _normalise_abha, _get_patient_or_404")

# --------------------------------------- duplicate guard inside link_abha
OLD_GUARD_ANCHOR = """    # Try verifying with ABDM — gracefully degrade if gateway is down
    gateway_result = await _verify_with_gateway(payload.abha_number)"""
NEW_GUARD = """    # An ABHA belongs to exactly one person. patients.abha_number is UNIQUE, so
    # without this the collision surfaces as an IntegrityError 500 rather than
    # something a receptionist can act on.
    normalised = _normalise_abha(payload.abha_number)
    clash = (await db.execute(
        select(Patient.id).where(
            Patient.abha_number == normalised,
            Patient.id != payload.patient_id,
        )
    )).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(409, {
            "code": "duplicate_abha",
            "message": "This ABHA number is already linked to another patient",
        })

    # Try verifying with ABDM — gracefully degrade if gateway is down
    gateway_result = await _verify_with_gateway(payload.abha_number)"""

if "duplicate_abha" not in text and OLD_GUARD_ANCHOR in text:
    text = text.replace(OLD_GUARD_ANCHOR, NEW_GUARD, 1)
    print("+ duplicate-ABHA 409 guard in link_abha")

# --------------------------------------------------------- get / unlink
ENDPOINTS = '''

@router.get(
    "/patients/{patient_id}/abha",
    response_model=AbhaOut,
    dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "admin"))],
)
async def get_abha(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> AbhaOut:
    """Read a patient's linked ABHA. Facility-scoped via _get_patient_or_404."""
    patient = await _get_patient_or_404(db, patient_id, current_db_user.facility_id)
    return AbhaOut(patient_id=patient.id, abha_number=patient.abha_number)


@router.delete(
    "/patients/{patient_id}/abha",
    response_model=AbhaOut,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def unlink_abha(
    patient_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> AbhaOut:
    """Unlink an ABHA, clearing the encrypted token with it.

    All three columns go together. Clearing abha_number alone would leave
    abha_linking_token_encrypted and abha_linking_key_version populated — an
    encrypted ABDM token for a link that no longer exists, which is the exact
    half-record state 0030's both-or-neither CHECK exists to prevent, and a
    DPDP problem besides: we would be retaining an identity credential after
    the relationship it belonged to was severed.
    """
    patient = await _get_patient_or_404(db, patient_id, current_db_user.facility_id)

    if patient.abha_number is None:
        raise HTTPException(409, {
            "code": "no_abha_linked",
            "message": "Patient has no ABHA number linked",
        })

    patient.abha_number = None
    patient.abha_linking_token_encrypted = None
    patient.abha_linking_key_version = None
    patient.abha_linked_at = None
    patient.updated_by = current_db_user.id
    await db.flush()

    await enqueue(
        db,
        aggregate_type="patient",
        aggregate_id=str(patient.id),
        event_type="abha_unlinked",
        payload={},
        sensitivity="important",
    )
    await db.refresh(patient)
    return AbhaOut(patient_id=patient.id, abha_number=None)
'''

if "async def unlink_abha" not in text:
    text = text.rstrip("\n") + "\n" + ENDPOINTS
    print("+ get_abha, unlink_abha")

ROUTER.write_text(text)
print("\nwrote", ROUTER)

# ------------------------------------------- Patient's missing 0030 columns
#
# unlink sets these to NULL, and SQLAlchemy will not complain if they are not
# mapped — it just sets a plain Python attribute and emits no UPDATE. The
# unlink would silently leave the encrypted token in the database, which is
# the worst of the three possible outcomes.
#
# This is the gap #353's empty 0038 migration was trying to record. It was
# right about the problem: 0030 added three columns and the ORM never declared
# them. A migration cannot fix that — it is a model change.
MODELS = pathlib.Path("backend/app/patients/models.py")
OLD_COL = ('    abha_number: Mapped[str | None] = '
           'mapped_column(String(17), unique=True, nullable=True)')
NEW_COL = OLD_COL + '''
    # Added by 0030 and never declared here — see #353. Both-or-neither is
    # enforced by ck_patients_abha_token_key_version, so they are always
    # written and cleared together.
    abha_linking_token_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    abha_linking_key_version: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True
    )
    abha_linked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )'''

if MODELS.exists():
    mtext = MODELS.read_text()
    if "abha_linking_token_encrypted" in mtext:
        print("~ Patient already declares the 0030 columns")
    elif OLD_COL in mtext:
        mtext = mtext.replace(OLD_COL, NEW_COL, 1)
        for sym, mod in (("LargeBinary", "sqlalchemy"), ("SmallInteger", "sqlalchemy")):
            # crude but adequate: these files import symbols from sqlalchemy in
            # one grouped statement
            import re as _re
            m = _re.search(r"^from sqlalchemy import \(([^)]*)\)", mtext, _re.M | _re.S)
            if m and sym not in m.group(1):
                mtext = mtext[:m.start(1)] + m.group(1).rstrip() + f", {sym}\n" + mtext[m.end(1):]
            elif not m:
                m2 = _re.search(r"^from sqlalchemy import (.+)$", mtext, _re.M)
                if m2 and sym not in m2.group(1):
                    mtext = mtext.replace(m2.group(0), m2.group(0) + f", {sym}", 1)
        MODELS.write_text(mtext)
        print("+ Patient: abha_linking_token_encrypted, abha_linking_key_version, abha_linked_at")
        print("  (check the sqlalchemy import line — LargeBinary/SmallInteger/DateTime/datetime)")
    else:
        print("! could not find abha_number on Patient — add the three columns by hand")

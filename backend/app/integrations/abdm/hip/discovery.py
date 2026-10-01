"""Find the patient a PHR discovery request describes when no ABHA is bound here.

M2 USER_INIT_LINK_603: "HIP searches their records for any of the verified
identifiers; most commonly search should be first done on ABHA address; if no
match then search with Mobile number. On mobile number match HIP to do a fuzzy
logic match on matched records." This is also how a patient reached by the
deep-link SMS (HIP_INIT_NOTIFY_HIECM) finds the record: they registered here
with name, date of birth, gender and mobile, and no ABHA address.

Only an unambiguous match is returned. Discovery answers with care-context
labels, and the link that follows sends its OTP to the mobile HealthDoc holds,
but a near miss still must not show one person's record list to another.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import date
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.abdm.contracts_v3 import DiscoveryPatient
from app.patients.models import Patient

_GENDERS = {"M": "male", "F": "female", "O": "other"}
_MOBILE_TYPES = {"MOBILE"}
_ABHA_NUMBER_TYPES = {"ABHA_NUMBER", "NDHM_HEALTH_NUMBER", "HEALTH_NUMBER"}
_RECORD_NUMBER_TYPES = {"MR"}
#: Names typed at two different desks differ by spelling, spacing and initials;
#: below this they are treated as different people. A subset of name tokens
#: ("Ram Kumar" vs "Ram Kumar Sharma") also matches.
_NAME_SIMILARITY = 0.85


def national_mobile(value: str | None) -> str | None:
    """Ten national digits from any Indian mobile spelling, else None."""
    digits = "".join(ch for ch in value or "" if ch.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) == 10 and digits[0] in "6789" else None


def _name_tokens(value: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", value).casefold()
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.findall(r"[a-z0-9]+", plain)


def names_match(declared: str | None, held: str | None) -> bool:
    a, b = _name_tokens(declared or ""), _name_tokens(held or "")
    if not a or not b:
        return False
    if set(a) <= set(b) or set(b) <= set(a):
        return True
    return SequenceMatcher(None, " ".join(a), " ".join(b)).ratio() >= _NAME_SIMILARITY


def _year_matches(declared: str | None, patient: Patient, today: date) -> bool:
    try:
        year = int(declared or "")
    except ValueError:
        return False
    if patient.dob is not None:
        return patient.dob.year == year
    # Age-only registration: the birth year is known to within one year.
    if patient.age_years is not None:
        return abs((today.year - patient.age_years) - year) <= 1
    return False


def _identifiers(patient: DiscoveryPatient, types: set[str], verified: bool) -> list[str]:
    rows = patient.verified_identifiers if verified else patient.unverified_identifiers
    return [
        row.value.strip()
        for row in rows
        if row.value and (row.type or "").strip().upper() in types
    ]


async def match_by_demographics(
    db: AsyncSession, *, facility_id: uuid.UUID, wire: DiscoveryPatient, today: date
) -> tuple[Patient | None, list[str]]:
    """Return (patient, matchedBy) for a single safe match, else (None, [])."""
    mobiles = {m for m in map(national_mobile, _identifiers(wire, _MOBILE_TYPES, True)) if m}
    gender = _GENDERS.get((wire.gender or "").strip().upper())
    if len(mobiles) != 1 or gender is None:
        return None, []
    mobile = mobiles.pop()
    abha_numbers = {
        value.replace("-", "") for value in _identifiers(wire, _ABHA_NUMBER_TYPES, True)
    }
    rows = (
        await db.execute(
            select(Patient).where(
                Patient.facility_id == facility_id,
                Patient.deleted_at.is_(None),
                Patient.merged_into_patient_id.is_(None),
                # A chart bound to some ABHA address is found by that address
                # or not at all: never hand it to a different address.
                Patient.abha_address.is_(None),
                Patient.mobile.like(f"%{mobile}"),
            )
        )
    ).scalars().all()
    candidates = [
        patient
        for patient in rows
        if national_mobile(patient.mobile) == mobile
        and patient.sex == gender
        and _year_matches(wire.year_of_birth, patient, today)
        and names_match(wire.name, patient.full_name)
        # A chart that already holds an ABHA number must hold this one.
        and (patient.abha_number is None or patient.abha_number in abha_numbers)
    ]
    if len(candidates) > 1:
        # A record number the user declared (unverified) may only narrow a
        # verified match, never create one.
        declared = set(_identifiers(wire, _RECORD_NUMBER_TYPES, False))
        narrowed = [p for p in candidates if p.uhid and p.uhid in declared]
        if len(narrowed) == 1:
            return narrowed[0], ["MOBILE", "MR"]
        return None, []
    if len(candidates) == 1:
        return candidates[0], ["MOBILE"]
    return None, []


#: How long a demographic match stays quotable by a link-init.
MATCH_TTL_MINUTES = 30


def match_id(facility_id: uuid.UUID, transaction_id: str) -> uuid.UUID:
    return uuid.uuid5(facility_id, f"abdm-discovery:{transaction_id}")


def verified_abha_number(wire: DiscoveryPatient) -> str | None:
    numbers = {
        digits
        for value in _identifiers(wire, _ABHA_NUMBER_TYPES, True)
        if len(digits := "".join(ch for ch in value if ch.isdigit())) == 14
    }
    return numbers.pop() if len(numbers) == 1 else None


async def record_match(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    transaction_id: str,
    wire: DiscoveryPatient,
    patient: Patient,
    references: list[str],
    matched_by: list[str],
    now,
) -> None:
    """Keep what a link-init for this transaction may quote. First write wins."""
    from datetime import timedelta

    from app.integrations.abdm.hip.models import AbdmDiscoveryMatch

    ident = match_id(facility_id, transaction_id)
    if await db.get(AbdmDiscoveryMatch, ident) is not None:
        return
    db.add(
        AbdmDiscoveryMatch(
            id=ident,
            facility_id=facility_id,
            patient_id=patient.id,
            transaction_id=transaction_id,
            abha_address=wire.id,
            abha_number=verified_abha_number(wire),
            care_context_references=sorted(references),
            matched_by=matched_by,
            expires_at=now + timedelta(minutes=MATCH_TTL_MINUTES),
        )
    )
    await db.flush()


async def discovered_patient(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    transaction_id: str,
    abha_address: str,
    requested: set[str],
    now,
) -> Patient | None:
    """The chart a recent demographic discovery matched for this exact ask."""
    from app.integrations.abdm.hip.models import AbdmDiscoveryMatch

    match = await db.get(AbdmDiscoveryMatch, match_id(facility_id, transaction_id))
    expires = match.expires_at if match else None
    if (
        match is None
        or match.facility_id != facility_id
        or match.abha_address != abha_address
        or not requested
        or not requested <= set(match.care_context_references)
        or (expires if expires.tzinfo else expires.replace(tzinfo=now.tzinfo)) <= now
    ):
        return None
    patient = await db.get(Patient, match.patient_id)
    if (
        patient is None
        or patient.facility_id != facility_id
        or patient.deleted_at is not None
        or patient.merged_into_patient_id is not None
        or patient.abha_address not in (None, abha_address)
    ):
        return None
    return patient


async def link_began_from_match(db: AsyncSession, link) -> bool:
    """True when this link's transaction is a demographic discovery of its chart."""
    from app.integrations.abdm.hip.models import AbdmDiscoveryMatch

    if not link.transaction_id:
        return False
    match = await db.get(AbdmDiscoveryMatch, match_id(link.facility_id, link.transaction_id))
    return (
        match is not None
        and match.facility_id == link.facility_id
        and match.patient_id == link.patient_id
        and match.abha_address == link.abha_address
    )


async def bind_confirmed_identity(
    db: AsyncSession, *, patient: Patient, abha_address: str, transaction_id: str | None, now
) -> bool:
    """Record the ABHA a confirmed, OTP-verified link proved for a mobile-only chart.

    M2 HIP_INIT_NOTIFY_HIECM: "After being linked, the record must be visible
    in their HIMS along with the ABHA Address and ABHA Number." The CM verified
    the address; the HIP's OTP went to the mobile this chart holds. Nothing is
    recorded if the chart already holds an address, or if another chart holds
    this address or number: both are unique, and overwriting either is a desk
    decision, not a callback's.
    """
    from app.integrations.abdm.hip.models import AbdmDiscoveryMatch

    if patient.abha_address is not None:
        return False
    held = (
        await db.execute(
            select(Patient.id).where(Patient.abha_address == abha_address, Patient.id != patient.id)
        )
    ).first()
    if held is not None:
        return False
    match = (
        await db.get(AbdmDiscoveryMatch, match_id(patient.facility_id, transaction_id))
        if transaction_id
        else None
    )
    number = match.abha_number if match and match.patient_id == patient.id else None
    if number is not None and (
        (patient.abha_number not in (None, number))
        or (
            await db.execute(
                select(Patient.id).where(Patient.abha_number == number, Patient.id != patient.id)
            )
        ).first()
        is not None
    ):
        number = None
    patient.abha_address = abha_address
    if number is not None:
        patient.abha_number = number
    patient.abha_linked_at = now
    await db.flush()
    return True

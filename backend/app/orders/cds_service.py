"""Rule-based CDS stub (#229, B3-W6-01): interaction flag + allergy
check on prescription save.

This is explicitly a stub per the issue title -- a small hardcoded
table of well-known interacting drug pairs, not a connection to a
real drug database (e.g. RxNorm/DDInter). Flags are informational
only: they never block a prescription from saving. Per the
architecture doc's AI-safety framing (§37, "AI suggestions should
always be marked as suggestions and require human review"), the same
principle applies here even though this isn't AI -- a rule-based flag
is a suggestion for the reviewing clinician, not a hard gate.
"""
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.patients.models import PatientAllergy

# Small illustrative set of well-known interacting pairs. Names are
# matched case-insensitively as substrings, not exact drug codes --
# this is a stub, not a real interaction database.
_KNOWN_INTERACTIONS: set[frozenset[str]] = {
    frozenset({"warfarin", "aspirin"}),
    frozenset({"warfarin", "ibuprofen"}),
    frozenset({"ace inhibitor", "potassium"}),
    frozenset({"sildenafil", "nitrate"}),
    frozenset({"maoi", "ssri"}),
    frozenset({"methotrexate", "trimethoprim"}),
}


def _normalize(name: str) -> str:
    return name.strip().lower()


def check_interactions(medicine_names: list[str]) -> list[dict]:
    """Pairwise check of the given medicine names against the known
    interaction table. O(n^2) over a prescription's items, which is
    fine at stub scale (a prescription has a handful of items)."""
    flags = []
    normalized = [(name, _normalize(name)) for name in medicine_names]
    for i in range(len(normalized)):
        for j in range(i + 1, len(normalized)):
            name_a, norm_a = normalized[i]
            name_b, norm_b = normalized[j]
            for pair in _KNOWN_INTERACTIONS:
                a, b = tuple(pair)
                if (a in norm_a and b in norm_b) or (a in norm_b and b in norm_a):
                    flags.append({
                        "type": "interaction",
                        "drug_a": name_a,
                        "drug_b": name_b,
                        "message": f"Potential interaction between {name_a} and {name_b}",
                    })
    return flags


async def check_allergies(
    db: AsyncSession, patient_id: uuid.UUID, medicine_names: list[str]
) -> list[dict]:
    """Check the given medicine names against the patient's recorded
    allergies (substring match, case-insensitive)."""
    stmt = select(PatientAllergy).where(PatientAllergy.patient_id == patient_id)
    result = await db.execute(stmt)
    allergies = result.scalars().all()
    if not allergies:
        return []

    flags = []
    for medicine_name in medicine_names:
        norm_med = _normalize(medicine_name)
        for allergy in allergies:
            norm_allergen = _normalize(allergy.allergen)
            if norm_allergen in norm_med or norm_med in norm_allergen:
                flags.append({
                    "type": "allergy",
                    "medicine_name": medicine_name,
                    "allergen": allergy.allergen,
                    "reaction": allergy.reaction,
                    "message": f"Patient has a recorded allergy to {allergy.allergen}",
                })
    return flags

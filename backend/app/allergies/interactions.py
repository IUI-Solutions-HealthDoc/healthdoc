"""Rule-based interaction flag — #229 (B3-W6-01), stub.

Unlike the allergy check (app.allergies.service.check_prescription_item),
this NEVER blocks a save. It is deliberately a stub: a small hardcoded
table of known-conflicting ingredient-code pairs, checked across all
items on one prescription at save time. A real interaction engine
(dose-dependent severity, a proper drug-interaction database, e.g.
DrugBank/First Databank style tiers) is out of scope here -- this
exists so the prescribing screen shows *something* today instead of
nothing, and so the shape (ingredient-code pairs in, warning strings
out) is already right when a real rules table replaces
_KNOWN_INTERACTIONS later.

Matching is on ingredient_code, same reasoning as the allergy check:
two different inventory_items rows (e.g. two brands of the same
ingredient) must both trigger the same warning.
"""
from __future__ import annotations

from itertools import combinations

#: (ingredient_a, ingredient_b) -> human-readable warning. Stored as an
#: unordered frozenset key so lookup doesn't care which item was listed
#: first on the prescription. This is a STUB list -- a handful of
#: well-known, high-teaching-value pairs, not a clinical reference.
#: Extend via a real interaction database, not by hand-adding rows here,
#: once one is wired in.
_KNOWN_INTERACTIONS: dict[frozenset[str], str] = {
    frozenset({"WARFARIN", "ASPIRIN"}): "Warfarin + Aspirin: increased bleeding risk.",
    frozenset({"WARFARIN", "IBUPROFEN"}): "Warfarin + Ibuprofen (NSAID): increased bleeding risk.",
    frozenset({"ACE_INHIBITOR", "POTASSIUM_SPARING_DIURETIC"}):
        "ACE inhibitor + potassium-sparing diuretic: risk of hyperkalaemia.",
    frozenset({"METFORMIN", "IODINATED_CONTRAST"}):
        "Metformin + iodinated contrast: risk of lactic acidosis; hold metformin around contrast studies.",
    frozenset({"MAOI", "SSRI"}): "MAOI + SSRI: risk of serotonin syndrome.",
}


def check_interactions(ingredient_codes: list[str | None]) -> list[str]:
    """Check every pair of ingredients on one prescription against the
    known-conflict table. Non-blocking by design -- returns warning
    strings for the caller to surface, never raises.

    None entries (an item with no resolved ingredient_code) are dropped
    silently, same "cannot check, so don't claim to" stance as
    check_prescription_item -- an unknown ingredient is not a match,
    it's an unmatchable item.
    """
    codes = [c for c in ingredient_codes if c is not None]
    warnings: list[str] = []
    for a, b in combinations(sorted(set(codes)), 2):
        message = _KNOWN_INTERACTIONS.get(frozenset({a, b}))
        if message is not None:
            warnings.append(message)
    return warnings

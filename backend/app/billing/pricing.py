"""
Pricing lookups for the invoice builder (B7-W2-01).

IMPORTANT — flag for code review:
The v3.4.1 schema doc has no service/price-catalog table (no
`service_prices`, no per-item tariff on inventory_items beyond
purchase_rate/issue_rate_mrp on inventory_batches for pharmacy stock).
Rather than invent a new migration inside a "build the invoice
aggregator" ticket, this module isolates every price lookup behind the
functions below so that:

  1. The invoice builder itself (service.py) never hardcodes a price —
     it always calls into this module.
  2. When a real pricing/tariff table lands (facility-configurable,
     matching the "government scheme coverage must be configurable,
     not hardcoded" rule that already applies to scheme_code), only
     this file changes.

Until then, prices come from two places:
  - PHARMACY: inventory_batches.issue_rate_mrp (already in the schema,
    already facility-editable via inventory ops) — real, not a stub.
  - LAB / RADIOLOGY / other: a static in-memory table below — a real
    stub. Anything not listed returns priced=False rather than
    guessing, so unpriced work is never silently billed at ₹0 or made
    up by app code.

Do not extend the static tables below with real hospital tariffs —
that data belongs in a DB-backed catalog, not source code. This is
placeholder data for dev/test only.

PR REVIEW (2 days ago, solutionsiui) — pricing.py is superseded, not
rewritten:
Schema v3.14 adds `charge_master` (migration 0033, #285, owned by
solutionsiui) — effective-dated tariffs, scheme_code for PM-JAY rates,
price superseded by insert so history is reconstructible; invoice_items
gains charge_master_id. That migration hasn't landed in this branch yet
(0014 is still the latest billing migration here), and its exact column
names aren't confirmed anywhere available to this module — repointing
the functions below to query `charge_master` NOW would mean guessing at
a schema this file has no authoritative source for, which is exactly
the mistake this module's isolation was built to avoid in the first
place.

What IS safe to do now, and is done: nothing changes about the public
functions' signatures or the PriceResult contract, so the swap the
reviewer asked for — "repoint pricing.py at charge_master" — really
will be a small, isolated diff to this file's internals once 0033 is
rebased in and its real column names are visible. service.py (the only
caller) never needs to change. Two rules already agreed with the
reviewer, worth restating here so whoever makes that later diff doesn't
relitigate them: unit_price must be copied onto the invoice_items row
at accrual time, never joined at read time (a later tariff revision
must not retroactively change an issued invoice); and a charge with no
matching tariff row must stay priced=False, never become a silent
₹0 line.
"""

from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple


class PriceResult(NamedTuple):
    unit_price: Decimal | None
    note: str | None


# Static stand-in for a future `lab_test_prices` / `radiology_tariffs`
# style table. Keyed by the natural code already on the source row
# (test_code / modality) since that's the only stable key we have
# without a real catalog.
_LAB_TEST_PRICES: dict[str, Decimal] = {
    "CBC": Decimal("300.00"),
    "LFT": Decimal("500.00"),
    "KFT": Decimal("500.00"),
    "BLOOD_SUGAR_F": Decimal("100.00"),
    "URINE_RE": Decimal("150.00"),
}

_RADIOLOGY_MODALITY_PRICES: dict[str, Decimal] = {
    "xray": Decimal("300.00"),
    "usg": Decimal("800.00"),
    "ct": Decimal("2500.00"),
    "mri": Decimal("4500.00"),
    "mammo": Decimal("1200.00"),
}


def price_lab_test(test_code: str | None) -> PriceResult:
    if not test_code or test_code not in _LAB_TEST_PRICES:
        return PriceResult(None, f"no tariff configured for lab test_code={test_code!r}")
    return PriceResult(_LAB_TEST_PRICES[test_code], None)


def price_radiology_modality(modality: str | None) -> PriceResult:
    if not modality or modality not in _RADIOLOGY_MODALITY_PRICES:
        return PriceResult(None, f"no tariff configured for radiology modality={modality!r}")
    return PriceResult(_RADIOLOGY_MODALITY_PRICES[modality], None)


def price_pharmacy_batch(issue_rate_mrp: Decimal | None) -> PriceResult:
    """Pharmacy pricing is real (inventory_batches.issue_rate_mrp), not a stub.

    Still routed through this module so callers never read the price
    column directly — keeps every invoice_items.unit_price decision in
    one place, which matters for billing's CRITICAL sync sensitivity.
    """
    if issue_rate_mrp is None:
        return PriceResult(None, "batch has no issue_rate_mrp set")
    return PriceResult(issue_rate_mrp, None)

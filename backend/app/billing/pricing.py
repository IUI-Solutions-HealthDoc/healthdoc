"""Batch-based pharmacy pricing.

Lab and radiology use the effective-dated facility charge_master through
billing.service. There are no sample service prices in runtime code.
"""
from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple


class PriceResult(NamedTuple):
    unit_price: Decimal | None
    note: str | None


def price_pharmacy_batch(issue_rate_mrp: Decimal | None) -> PriceResult:
    """Use the recorded batch rate; missing is unpriced, never an assumed zero."""
    if issue_rate_mrp is None:
        return PriceResult(None, "batch has no issue_rate_mrp set")
    return PriceResult(issue_rate_mrp, None)

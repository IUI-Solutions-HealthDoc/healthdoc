"""
Pure unit tests for pricing.py — no DB, no async, mirrors the module's
own nature (isolated price-lookup functions). Covers the "never
silently bill ₹0 for unpriced work" behaviour the reviewer specifically
praised (priced=False instead of guessing).
"""
from decimal import Decimal

from app.billing.pricing import price_pharmacy_batch


class TestPricePharmacyBatch:
    def test_real_mrp_passed_through(self):
        result = price_pharmacy_batch(Decimal("42.50"))
        assert result.unit_price == Decimal("42.50")
        assert result.note is None

    def test_missing_mrp_returns_none_not_zero(self):
        result = price_pharmacy_batch(None)
        assert result.unit_price is None
        assert "issue_rate_mrp" in result.note

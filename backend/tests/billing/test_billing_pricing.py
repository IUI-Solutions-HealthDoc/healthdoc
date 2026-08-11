"""
Pure unit tests for pricing.py — no DB, no async, mirrors the module's
own nature (isolated price-lookup functions). Covers the "never
silently bill ₹0 for unpriced work" behaviour the reviewer specifically
praised (priced=False instead of guessing).
"""
from decimal import Decimal

from app.billing.pricing import (
    price_lab_test,
    price_pharmacy_batch,
    price_radiology_modality,
)


class TestPriceLabTest:
    def test_known_code_returns_price(self):
        result = price_lab_test("CBC")
        assert result.unit_price == Decimal("300.00")
        assert result.note is None

    def test_unknown_code_returns_none_not_zero(self):
        result = price_lab_test("SOME_MADE_UP_TEST")
        assert result.unit_price is None
        assert result.note is not None

    def test_none_code_returns_none(self):
        result = price_lab_test(None)
        assert result.unit_price is None


class TestPriceRadiologyModality:
    def test_known_modality_returns_price(self):
        result = price_radiology_modality("mri")
        assert result.unit_price == Decimal("4500.00")

    def test_unknown_modality_returns_none(self):
        result = price_radiology_modality("teleporter_scan")
        assert result.unit_price is None
        assert result.note is not None


class TestPricePharmacyBatch:
    def test_real_mrp_passed_through(self):
        result = price_pharmacy_batch(Decimal("42.50"))
        assert result.unit_price == Decimal("42.50")
        assert result.note is None

    def test_missing_mrp_returns_none_not_zero(self):
        result = price_pharmacy_batch(None)
        assert result.unit_price is None
        assert "issue_rate_mrp" in result.note

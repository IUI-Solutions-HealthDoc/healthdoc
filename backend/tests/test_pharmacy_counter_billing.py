"""A pharmacy counter bills dispensed medicines, and nothing else.

Role gating alone cannot express this. There is one invoice per visit (schema
§3 0014), so the invoice a pharmacist touches can also carry consultation, lab
and bed charges — letting them settle it would be letting them collect for all
of it. The rule is therefore checked against what is ON the invoice.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.billing.router import _assert_invoice_is_pharmacy_only, _is_pharmacy_counter


class _User:
    def __init__(self, *roles: str):
        self.roles = list(roles)


@pytest.mark.parametrize(
    "roles, restricted",
    [
        (("pharmacist",), True),
        # Holding the desk role as well lifts the restriction: the narrower
        # rule exists to stop a pharmacy counter settling a consultation, not
        # to punish somebody for holding two roles.
        (("pharmacist", "billing"), False),
        (("pharmacist", "admin"), False),
        (("billing",), False),
        (("admin",), False),
    ],
)
def test_who_the_pharmacy_scope_applies_to(roles, restricted):
    assert _is_pharmacy_counter(_User(*roles)) is restricted


class _Result:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class _Db:
    def __init__(self, categories):
        self._categories = categories

    async def execute(self, *_args, **_kwargs):
        return _Result(self._categories)


@pytest.mark.asyncio
async def test_a_pharmacy_only_invoice_may_be_settled():
    await _assert_invoice_is_pharmacy_only(_Db(["pharmacy", "pharmacy"]), uuid.uuid4())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "categories, mentioned",
    [
        (["pharmacy", "consultation"], "consultation"),
        (["pharmacy", "lab"], "lab"),
        (["registration", "pharmacy"], "registration"),
        (["ipd_stay"], "ipd_stay"),
    ],
)
async def test_a_mixed_invoice_is_refused_and_says_why(categories, mentioned):
    with pytest.raises(HTTPException) as exc:
        await _assert_invoice_is_pharmacy_only(_Db(categories), uuid.uuid4())
    assert exc.value.status_code == 403
    # The message names the offending categories: "forbidden" with no reason
    # sends a pharmacist to the billing desk without knowing what to say.
    assert mentioned in exc.value.detail


@pytest.mark.asyncio
async def test_an_empty_invoice_is_a_conflict_not_a_silent_pass():
    """An invoice with no lines is not a pharmacy invoice.

    409 rather than 403: nothing is forbidden, the work simply has not been
    done yet, and a pharmacist told "forbidden" would go looking for a
    permission problem that does not exist.
    """
    with pytest.raises(HTTPException) as exc:
        await _assert_invoice_is_pharmacy_only(_Db([]), uuid.uuid4())
    assert exc.value.status_code == 409


def test_the_pharmacy_counter_may_append_only_medicines():
    """The other half of the rule.

    Refusing to SETTLE a mixed invoice is not enough. Without this, a
    pharmacist calling build would sweep the visit's consultation, lab and
    radiology charges onto the invoice as a side effect of billing a strip of
    tablets — and would then be locked out of the invoice they had just made
    mixed.
    """
    from decimal import Decimal

    from app.billing.schemas import ChargeLine
    from app.billing.service import restrict_to_categories
    from app.common.enums import ChargeCategory

    def line(category: ChargeCategory) -> ChargeLine:
        return ChargeLine(
            charge_category=category,
            reference_type="test",
            reference_id=uuid.uuid4(),
            description=f"{category.value} line",
            unit_price=Decimal("10"),
            amount=Decimal("10"),
        )

    everything = [
        line(ChargeCategory.PHARMACY),
        line(ChargeCategory.CONSULTATION),
        line(ChargeCategory.LAB),
        line(ChargeCategory.RADIOLOGY),
        line(ChargeCategory.REGISTRATION),
    ]

    scoped = restrict_to_categories(everything, frozenset({ChargeCategory.PHARMACY.value}))
    assert [l.charge_category.value for l in scoped] == ["pharmacy"]

    # None means the billing desk, which still bills the whole visit. The
    # filter narrows for one caller; it does not become everyone's default.
    assert restrict_to_categories(everything, None) == everything

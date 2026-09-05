from decimal import Decimal

import pytest

from apps.models import CurrencyCode
from apps.money import (
    calculate_invoice_total,
    calculate_ratio_cost,
    calculate_ratio_unit_price,
    require_ledger_amount,
    require_quantity,
)


def test_orange_ratio_preserves_reference_amounts():
    assert calculate_ratio_cost(
        quantity=10650, amount=100, units=10650
    ) == Decimal("100.000000000000")
    assert calculate_ratio_cost(
        quantity=15975, amount=100, units=10650
    ) == Decimal("150.000000000000")


def test_orange_display_unit_price_does_not_drive_exact_cost():
    assert calculate_ratio_unit_price(
        amount=100, units=10650
    ) == Decimal("0.009389671362")
    assert calculate_ratio_cost(
        quantity=12000, amount=100, units=10650
    ) == Decimal("112.676056338028")


def test_currency_specific_invoice_rounding():
    lines = [Decimal("5625"), Decimal("5625")]
    assert calculate_invoice_total(lines, CurrencyCode.CDF) == Decimal("11250")
    assert calculate_invoice_total(
        [Decimal("47.225"), Decimal("47.225")], CurrencyCode.USD
    ) == Decimal("94.45")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "not-a-number"])
def test_ledger_amount_rejects_non_finite_or_invalid_values(value):
    with pytest.raises(ValueError):
        require_ledger_amount(value, label="Le montant", allow_zero=True)


@pytest.mark.parametrize("value", ["1.5", "NaN", "2147483648"])
def test_quantity_rejects_fractional_non_finite_and_oversized_values(value):
    with pytest.raises(ValueError):
        require_quantity(value)

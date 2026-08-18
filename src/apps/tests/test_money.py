from decimal import Decimal

from apps.models import CurrencyCode
from apps.money import (
    calculate_invoice_total,
    calculate_ratio_cost,
    calculate_ratio_unit_price,
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

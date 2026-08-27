"""Exact, currency-aware calculations shared by all transaction paths."""

from decimal import Decimal, ROUND_HALF_UP

from apps.models import CurrencyCode


UNIT_PRICE_QUANTUM = Decimal("0.000000000001")
INTERNAL_MONEY_QUANTUM = Decimal("0.000000000001")


def as_decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def quantize_unit_price(value) -> Decimal:
    return as_decimal(value).quantize(UNIT_PRICE_QUANTUM, rounding=ROUND_HALF_UP)


def format_unit_price(value, *, minimum_places=5) -> str:
    """Show enough stored precision to reproduce a line total."""
    rendered = f"{as_decimal(value):.12f}".rstrip("0")
    whole, _, fraction = rendered.partition(".")
    if len(fraction) < minimum_places:
        fraction = fraction.ljust(minimum_places, "0")
    return f"{whole}.{fraction}"


def calculate_ratio_unit_price(*, amount, units) -> Decimal:
    units = as_decimal(units)
    if units <= 0:
        raise ValueError("Le nombre d'unités doit être positif.")
    return quantize_unit_price(as_decimal(amount) / units)


def calculate_ratio_cost(*, quantity, amount, units) -> Decimal:
    """Calculate from the exact ratio, not its display-rounded unit price."""
    units = as_decimal(units)
    if units <= 0:
        raise ValueError("Le nombre d'unités doit être positif.")
    return (as_decimal(quantity) * as_decimal(amount) / units).quantize(
        INTERNAL_MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )


def round_payable(value, currency_code: CurrencyCode) -> Decimal:
    value = as_decimal(value)
    if currency_code == CurrencyCode.USD:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Existing CDF 0/50/100 rule, applied once to the complete invoice.
    whole = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    remainder = whole % 100
    if remainder == 0:
        return whole
    if remainder < 25:
        return whole - remainder
    if remainder <= 50:
        return whole - remainder + 50
    return whole - remainder + 100


def calculate_invoice_total(raw_subtotals, currency_code: CurrencyCode) -> Decimal:
    return round_payable(sum(map(as_decimal, raw_subtotals), Decimal("0")), currency_code)

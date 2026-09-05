"""Exact, currency-aware calculations and input limits."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from apps.models import CurrencyCode


UNIT_PRICE_QUANTUM = Decimal("0.000000000001")
INTERNAL_MONEY_QUANTUM = Decimal("0.000000000001")
MAX_QUANTITY = Decimal("2147483647")
MAX_LEDGER_AMOUNT = Decimal("9999999999.99")
MAX_INVENTORY_VALUE = Decimal("999999999999.999999999999")
PRICE_FACTOR_LIMIT = Decimal("10")


def as_decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def require_quantity(value, *, allow_zero=False) -> Decimal:
    """Return a finite whole quantity that fits all transaction tables."""
    try:
        quantity = as_decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Saisissez une quantité valide.") from error
    minimum = Decimal("0") if allow_zero else Decimal("1")
    if (
        not quantity.is_finite()
        or quantity < minimum
        or quantity != quantity.to_integral_value()
    ):
        requirement = "nulle ou positive" if allow_zero else "positive"
        raise ValueError(f"La quantité doit être un nombre entier {requirement}.")
    if quantity > MAX_QUANTITY:
        raise ValueError("La quantité saisie est trop élevée. Corrigez-la.")
    return quantity


def require_ledger_amount(value, *, label="Le montant", allow_zero=False) -> Decimal:
    """Return a finite amount that fits the app's narrowest money columns."""
    try:
        amount = as_decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"{label} n'est pas valide.") from error
    minimum = Decimal("0") if allow_zero else Decimal("0.000000000001")
    if not amount.is_finite() or amount < minimum:
        requirement = "positif ou nul" if allow_zero else "positif"
        raise ValueError(f"{label} doit être {requirement}.")
    if amount > MAX_LEDGER_AMOUNT:
        raise ValueError(f"{label} est trop élevé. Corrigez la valeur saisie.")
    return amount


def require_comparable_unit_prices(*, cost, selling_price) -> None:
    """Reject likely currency/decimal mistakes between purchase and sale prices."""
    cost = require_ledger_amount(cost, label="Le prix d'achat")
    selling_price = require_ledger_amount(
        selling_price, label="Le prix de vente"
    )
    if not (
        cost / PRICE_FACTOR_LIMIT
        <= selling_price
        <= cost * PRICE_FACTOR_LIMIT
    ):
        raise ValueError(
            f"Les prix semblent incohérents ({cost:.8f}/u à l'achat et "
            f"{selling_price:.8f}/u à la vente). Corrigez les prix."
        )


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

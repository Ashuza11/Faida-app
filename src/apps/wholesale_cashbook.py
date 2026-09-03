"""Accounting helpers for the manual wholesale cashbook."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from apps.models import CurrencyCode, WholesaleCashDirection


MONEY_QUANTUM = Decimal("0.01")


class CashbookConversionError(ValueError):
    """Raised when a cashbook conversion request is not usable."""


def build_cashbook_totals(entries) -> dict:
    """Total movements in their original currencies without mixing ledgers."""
    totals = {
        code: {
            "inflow": Decimal("0"),
            "outflow": Decimal("0"),
            "balance": Decimal("0"),
        }
        for code in CurrencyCode
    }
    for entry in entries:
        key = (
            "inflow"
            if entry.direction == WholesaleCashDirection.INFLOW
            else "outflow"
        )
        totals[entry.currency_code][key] += entry.amount
    for values in totals.values():
        values["balance"] = values["inflow"] - values["outflow"]
    return totals


def convert_cashbook_totals(
    totals: dict, *, target_currency: CurrencyCode, cdf_per_usd
) -> dict:
    """Combine native totals for display using a non-destructive FX rate."""
    try:
        rate = Decimal(str(cdf_per_usd))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise CashbookConversionError("Le taux de change est invalide.") from error
    if not rate.is_finite() or rate <= 0:
        raise CashbookConversionError("Le taux de change doit être supérieur à zéro.")

    converted = {}
    for key in ("inflow", "outflow", "balance"):
        if target_currency == CurrencyCode.CDF:
            value = totals[CurrencyCode.CDF][key] + (
                totals[CurrencyCode.USD][key] * rate
            )
        else:
            value = totals[CurrencyCode.USD][key] + (
                totals[CurrencyCode.CDF][key] / rate
            )
        converted[key] = value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    converted["currency"] = target_currency
    converted["rate"] = rate
    return converted

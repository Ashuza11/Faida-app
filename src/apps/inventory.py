"""Atomic inventory quantity and valuation operations."""

from decimal import Decimal, ROUND_HALF_UP

from apps.models import Stock
from apps.money import INTERNAL_MONEY_QUANTUM, as_decimal, quantize_unit_price


def record_purchase(
    *, stock: Stock, quantity, actual_total_cost, quoted_unit_cost=None,
) -> None:
    quantity = as_decimal(quantity)
    actual_total_cost = as_decimal(actual_total_cost)
    if quantity <= 0 or actual_total_cost < 0:
        raise ValueError("La quantité et le coût d'achat doivent être valides.")

    old_value = as_decimal(stock.inventory_value or 0)
    new_balance = as_decimal(stock.balance or 0) + quantity
    new_value = (old_value + actual_total_cost).quantize(
        INTERNAL_MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )
    stock.balance = new_balance
    stock.inventory_value = new_value
    stock.average_cost_per_unit = quantize_unit_price(new_value / new_balance)
    stock.buying_price_per_unit = quantize_unit_price(
        quoted_unit_cost if quoted_unit_cost is not None
        else actual_total_cost / quantity
    )


def consume_stock(*, stock: Stock, quantity) -> tuple[Decimal, Decimal]:
    """Deduct quantity/value and return the immutable unit and total cost."""
    quantity = as_decimal(quantity)
    balance = as_decimal(stock.balance or 0)
    if quantity <= 0:
        raise ValueError("La quantité vendue doit être positive.")
    if quantity > balance:
        raise ValueError("Stock insuffisant.")

    unit_cost = as_decimal(stock.average_cost_per_unit or 0)
    if quantity == balance:
        # Consume the exact remaining value so tiny decimal residues cannot
        # survive after inventory reaches zero.
        cost_total = as_decimal(stock.inventory_value or 0)
    else:
        cost_total = (quantity * unit_cost).quantize(
            INTERNAL_MONEY_QUANTUM, rounding=ROUND_HALF_UP
        )

    stock.balance = balance - quantity
    stock.inventory_value = max(
        Decimal("0"), as_decimal(stock.inventory_value or 0) - cost_total
    )
    if stock.balance == 0:
        stock.inventory_value = Decimal("0")
        stock.average_cost_per_unit = Decimal("0")
    return unit_cost, cost_total


def restore_sale_cost(*, stock: Stock, quantity, cost_total) -> None:
    quantity = as_decimal(quantity)
    cost_total = as_decimal(cost_total)
    new_balance = as_decimal(stock.balance or 0) + quantity
    new_value = as_decimal(stock.inventory_value or 0) + cost_total
    stock.balance = new_balance
    stock.inventory_value = new_value
    stock.average_cost_per_unit = (
        quantize_unit_price(new_value / new_balance)
        if new_balance else Decimal("0")
    )


def reverse_purchase(*, stock: Stock, quantity, actual_total_cost) -> None:
    """Reverse a purchase only while its quantity and value are still present."""
    quantity = as_decimal(quantity)
    actual_total_cost = as_decimal(actual_total_cost)
    balance = as_decimal(stock.balance or 0)
    value = as_decimal(stock.inventory_value or 0)
    if quantity > balance or actual_total_cost > value:
        raise ValueError(
            "Cet achat a déjà été consommé; utilisez un ajustement d'inventaire."
        )
    new_balance = balance - quantity
    new_value = value - actual_total_cost
    stock.balance = new_balance
    stock.inventory_value = new_value
    stock.average_cost_per_unit = (
        quantize_unit_price(new_value / new_balance)
        if new_balance else Decimal("0")
    )

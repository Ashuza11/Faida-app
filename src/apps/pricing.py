"""Default and custom price preset behavior."""

from decimal import Decimal

from apps.models import (
    Business,
    BusinessType,
    NetworkType,
    PriceOperation,
    PricePreset,
)
from apps.money import calculate_ratio_cost, calculate_ratio_unit_price


WHOLESALE_SALE_PRICES = (
    Decimal("0.00936"),
    Decimal("0.00940"),
    Decimal("0.00945"),
    Decimal("0.00950"),
)


def seed_default_price_presets(business: Business) -> list[PricePreset]:
    """Attach initial wholesale choices; retail keeps its existing configuration."""
    if business.business_type != BusinessType.WHOLESALE:
        return []

    presets = []
    purchase_defaults = {
        NetworkType.AFRICEL: Decimal("0.00940"),
        NetworkType.AIRTEL: Decimal("0.00935"),
    }
    for network, value in purchase_defaults.items():
        presets.append(PricePreset(
            business=business,
            network=network,
            operation=PriceOperation.PURCHASE,
            label=f"Standard {network.value.capitalize()}",
            unit_price=value,
            is_default=True,
        ))

    # The user sees the short unit price; cost calculations use 100/10650.
    presets.append(PricePreset(
        business=business,
        network=NetworkType.ORANGE,
        operation=PriceOperation.PURCHASE,
        label="Standard Orange",
        unit_price=calculate_ratio_unit_price(amount=100, units=10650),
        ratio_amount=Decimal("100"),
        ratio_units=Decimal("10650"),
        is_default=True,
    ))

    for network in NetworkType:
        for order, value in enumerate(WHOLESALE_SALE_PRICES):
            presets.append(PricePreset(
                business=business,
                network=network,
                operation=PriceOperation.SALE,
                label=f"${value} / unité",
                unit_price=value,
                is_default=(value == Decimal("0.00940")),
                display_order=order,
            ))
    return presets


def calculate_preset_cost(preset: PricePreset, quantity) -> Decimal:
    if preset.ratio_amount is not None and preset.ratio_units is not None:
        return calculate_ratio_cost(
            quantity=quantity,
            amount=preset.ratio_amount,
            units=preset.ratio_units,
        )
    return Decimal(quantity) * preset.unit_price

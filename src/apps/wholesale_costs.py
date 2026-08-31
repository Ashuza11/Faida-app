"""Wholesale stock-cost validation and report anomaly detection."""

from decimal import Decimal

from apps.models import PriceOperation, PricePreset
from apps.money import as_decimal
from apps.user_messages import user_message


REFERENCE_FACTOR_LIMIT = Decimal("10")


def reference_unit_cost(*, business_id, network):
    for operation in (PriceOperation.PURCHASE, PriceOperation.SALE):
        preset = (
            PricePreset.query.filter_by(
                business_id=business_id,
                network=network,
                operation=operation,
                is_active=True,
            )
            .order_by(PricePreset.is_default.desc(), PricePreset.id)
            .first()
        )
        if preset is not None:
            return as_decimal(preset.unit_price)
    return None


def wholesale_unit_cost_is_plausible(*, business_id, network, unit_cost) -> bool:
    unit_cost = as_decimal(unit_cost)
    if unit_cost <= 0:
        return False
    reference = reference_unit_cost(business_id=business_id, network=network)
    if reference is None or reference <= 0:
        return True
    return (
        reference / REFERENCE_FACTOR_LIMIT
        <= unit_cost
        <= reference * REFERENCE_FACTOR_LIMIT
    )


def require_plausible_wholesale_unit_cost(*, business_id, network, unit_cost):
    if wholesale_unit_cost_is_plausible(
        business_id=business_id, network=network, unit_cost=unit_cost
    ):
        return
    raise ValueError(user_message(
        f"Le coût calculé (${as_decimal(unit_cost):.8f}/u) semble incorrect.",
        "Saisissez le montant total payé et vérifiez le stock avant de continuer.",
    ))


def sale_item_has_cost_anomaly(item) -> bool:
    cost = as_decimal(item.cost_per_unit_snapshot)
    selling_price = as_decimal(item.price_per_unit_applied)
    return (
        cost <= 0
        or selling_price <= 0
        or cost > selling_price * REFERENCE_FACTOR_LIMIT
    )

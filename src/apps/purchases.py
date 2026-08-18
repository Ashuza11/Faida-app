"""Business-scoped stock purchase transactions."""

from decimal import Decimal

from apps import db
from apps.inventory import record_purchase
from apps.models import (
    Business,
    BusinessApprovalStatus,
    BusinessType,
    NetworkType,
    PriceOperation,
    PricePreset,
    Stock,
    StockPurchase,
    User,
)
from apps.money import as_decimal, quantize_unit_price
from apps.pricing import calculate_preset_cost


def record_wholesale_purchase(
    *,
    business: Business,
    purchased_by: User,
    network: NetworkType,
    quantity,
    preset: PricePreset | None = None,
    custom_unit_cost=None,
) -> StockPurchase:
    """Record one exact USD purchase without crossing business boundaries."""
    if business.business_type != BusinessType.WHOLESALE:
        raise ValueError("Cette opération est réservée au registre grossiste.")
    if business.approval_status != BusinessApprovalStatus.APPROVED:
        raise PermissionError("L'entreprise grossiste n'est pas encore approuvée.")
    if business.owner_user_id != purchased_by.id:
        raise PermissionError("Seul le propriétaire peut enregistrer cet achat.")

    quantity = as_decimal(quantity)
    if quantity <= 0 or quantity != quantity.to_integral_value():
        raise ValueError("La quantité doit être un nombre entier positif.")

    if preset is not None:
        if (
            preset.business_id != business.id
            or preset.network != network
            or preset.operation != PriceOperation.PURCHASE
            or not preset.is_active
        ):
            raise ValueError("Le prix sélectionné ne correspond pas à cet achat.")
        unit_cost = preset.unit_price
        total_cost = calculate_preset_cost(preset, quantity)
    else:
        if custom_unit_cost is None:
            raise ValueError("Sélectionnez un prix ou saisissez un prix personnalisé.")
        unit_cost = quantize_unit_price(custom_unit_cost)
        if unit_cost <= 0:
            raise ValueError("Le prix d'achat doit être positif.")
        total_cost = quantity * unit_cost

    stock = (
        Stock.query.filter_by(business_id=business.id, network=network)
        .with_for_update()
        .one_or_none()
    )
    if stock is None:
        stock = Stock(
            vendeur_id=business.owner_user_id,
            business_id=business.id,
            network=network,
            balance=Decimal("0"),
            buying_price_per_unit=unit_cost,
            selling_price_per_unit=Decimal("0.00940"),
            inventory_value=Decimal("0"),
            average_cost_per_unit=Decimal("0"),
        )
        db.session.add(stock)

    record_purchase(
        stock=stock,
        quantity=quantity,
        actual_total_cost=total_cost,
        quoted_unit_cost=unit_cost,
    )
    purchase = StockPurchase(
        purchased_by=purchased_by,
        stock_item=stock,
        price_preset=preset,
        network=network,
        buying_price_at_purchase=unit_cost,
        selling_price_at_purchase=stock.selling_price_per_unit,
        actual_total_cost=total_cost,
        amount_purchased=int(quantity),
    )
    db.session.add(purchase)
    return purchase

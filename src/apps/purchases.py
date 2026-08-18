"""Business-scoped stock purchase transactions."""

from decimal import Decimal
from datetime import date, datetime, timezone

from apps import db
from apps.inventory import record_purchase, reverse_purchase
from apps.models import (
    Business,
    BusinessApprovalStatus,
    BusinessType,
    NetworkType,
    PriceOperation,
    PricePreset,
    Stock,
    StockPurchase,
    Sale,
    SaleItem,
    TransactionStatus,
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
    purchase_date: date | None = None,
) -> StockPurchase:
    """Record one exact USD purchase without crossing business boundaries."""
    if business.business_type != BusinessType.WHOLESALE:
        raise ValueError("Cette opération est réservée au registre grossiste.")
    if business.approval_status != BusinessApprovalStatus.APPROVED:
        raise PermissionError("Le mode grossiste n'est pas encore approuvé.")
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
        purchase_date=purchase_date or date.today(),
    )
    db.session.add(purchase)
    return purchase


def _validate_retail_owner(*, business: Business, user: User) -> None:
    if business.business_type != BusinessType.RETAIL:
        raise ValueError("Cette opération est réservée au registre de détail.")
    if business.owner_user_id != user.id:
        raise PermissionError("Seul le propriétaire peut gérer les achats.")


def _locked_stock(*, business: Business, network: NetworkType) -> Stock | None:
    return (
        Stock.query.filter_by(business_id=business.id, network=network)
        .with_for_update()
        .one_or_none()
    )


def record_retail_purchase(
    *,
    business: Business,
    purchased_by: User,
    network: NetworkType,
    quantity,
    unit_cost,
    intended_selling_price,
    purchase_date: date | None = None,
) -> StockPurchase:
    """Create a retail purchase inside exactly one business ledger."""
    _validate_retail_owner(business=business, user=purchased_by)
    quantity = as_decimal(quantity)
    unit_cost = quantize_unit_price(unit_cost)
    intended_selling_price = quantize_unit_price(intended_selling_price)
    if quantity <= 0 or quantity != quantity.to_integral_value():
        raise ValueError("La quantité doit être un nombre entier positif.")
    if unit_cost <= 0 or intended_selling_price <= 0:
        raise ValueError("Les prix d'achat et de vente doivent être positifs.")

    stock, total_cost = _apply_retail_stock(
        business=business,
        network=network,
        quantity=quantity,
        unit_cost=unit_cost,
        intended_selling_price=intended_selling_price,
    )
    purchase = StockPurchase(
        purchased_by=purchased_by,
        stock_item=stock,
        network=network,
        amount_purchased=int(quantity),
        buying_price_at_purchase=unit_cost,
        selling_price_at_purchase=intended_selling_price,
        actual_total_cost=total_cost,
        purchase_date=purchase_date or date.today(),
    )
    db.session.add(purchase)
    return purchase


def _apply_retail_stock(
    *, business, network, quantity, unit_cost, intended_selling_price
) -> tuple[Stock, Decimal]:
    stock = _locked_stock(business=business, network=network)
    if stock is None:
        stock = Stock(
            vendeur_id=business.owner_user_id,
            business_id=business.id,
            network=network,
            balance=Decimal("0"),
            buying_price_per_unit=unit_cost,
            selling_price_per_unit=intended_selling_price,
            inventory_value=Decimal("0"),
            average_cost_per_unit=Decimal("0"),
        )
        db.session.add(stock)

    total_cost = quantity * unit_cost
    record_purchase(
        stock=stock,
        quantity=quantity,
        actual_total_cost=total_cost,
        quoted_unit_cost=unit_cost,
    )
    stock.selling_price_per_unit = intended_selling_price
    return stock, total_cost


def replace_retail_purchase(
    *,
    purchase: StockPurchase,
    business: Business,
    updated_by: User,
    network: NetworkType,
    quantity,
    unit_cost,
    intended_selling_price,
) -> None:
    """Atomically reverse a retail purchase and apply its replacement."""
    _validate_retail_owner(business=business, user=updated_by)
    if purchase.stock_item.business_id != business.id:
        raise PermissionError("Cet achat appartient à un autre mode.")

    old_stock = purchase.stock_item
    reverse_purchase(
        stock=old_stock,
        quantity=purchase.amount_purchased,
        actual_total_cost=purchase.actual_total_cost,
    )
    quantity = as_decimal(quantity)
    unit_cost = quantize_unit_price(unit_cost)
    intended_selling_price = quantize_unit_price(intended_selling_price)
    if quantity <= 0 or quantity != quantity.to_integral_value():
        raise ValueError("La quantité doit être un nombre entier positif.")
    if unit_cost <= 0 or intended_selling_price <= 0:
        raise ValueError("Les prix d'achat et de vente doivent être positifs.")
    new_stock, total_cost = _apply_retail_stock(
        business=business,
        network=network,
        quantity=quantity,
        unit_cost=unit_cost,
        intended_selling_price=intended_selling_price,
    )
    purchase.stock_item = new_stock
    purchase.network = network
    purchase.amount_purchased = int(quantity)
    purchase.buying_price_at_purchase = unit_cost
    purchase.selling_price_at_purchase = intended_selling_price
    purchase.actual_total_cost = total_cost
    purchase.price_preset = None


def delete_retail_purchase(
    *, purchase: StockPurchase, business: Business, deleted_by: User
) -> None:
    """Reverse and remove a retail purchase from its owning ledger."""
    _validate_retail_owner(business=business, user=deleted_by)
    if purchase.stock_item.business_id != business.id:
        raise PermissionError("Cet achat appartient à un autre mode.")
    reverse_purchase(
        stock=purchase.stock_item,
        quantity=purchase.amount_purchased,
        actual_total_cost=purchase.actual_total_cost,
    )
    db.session.delete(purchase)


def reverse_wholesale_purchase(
    *, purchase: StockPurchase, business: Business, reversed_by: User, reason: str
) -> None:
    """Reverse an unconsumed wholesale purchase without deleting its audit row."""
    if business.business_type != BusinessType.WHOLESALE:
        raise ValueError("Cette opération est réservée au registre grossiste.")
    if business.owner_user_id != reversed_by.id:
        raise PermissionError("Seul le propriétaire peut annuler cet achat.")
    if purchase.stock_item.business_id != business.id:
        raise PermissionError("Cet achat appartient à un autre mode.")
    if purchase.status != TransactionStatus.ACTIVE:
        raise ValueError("Cet achat est déjà annulé.")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ValueError("Indiquez la raison de l'annulation.")

    later_sale_exists = (
        db.session.query(SaleItem.id)
        .join(Sale)
        .filter(
            Sale.business_id == business.id,
            Sale.status == TransactionStatus.ACTIVE,
            SaleItem.network == purchase.network,
            Sale.sale_date >= purchase.purchase_date,
        )
        .first()
        is not None
    )
    if later_sale_exists:
        raise ValueError(
            "Cet achat ne peut pas être annulé car ce stock a déjà pu être vendu."
        )
    reverse_purchase(
        stock=purchase.stock_item,
        quantity=purchase.amount_purchased,
        actual_total_cost=purchase.actual_total_cost,
    )
    purchase.status = TransactionStatus.REVERSED
    purchase.reversed_at = datetime.now(timezone.utc)
    purchase.reversed_by_id = reversed_by.id
    purchase.reversal_reason = reason

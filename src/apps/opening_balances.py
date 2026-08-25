"""Cost-aware retailer opening stock anchors."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func

from apps import db
from apps.models import (
    BusinessType,
    NetworkType,
    Sale,
    SaleItem,
    Stock,
    StockOpeningBalance,
    StockPurchase,
    TransactionStatus,
)
from apps.money import INTERNAL_MONEY_QUANTUM, as_decimal, quantize_unit_price


class OpeningBalanceError(ValueError):
    """Raised when an opening balance would rewrite dependent history."""


def save_opening_balances(*, business, recorded_by, balance_date, updates):
    """Upsert only submitted networks and reconcile today's inventory value."""
    if business.business_type != BusinessType.RETAIL:
        raise OpeningBalanceError("Le stock d'ouverture est réservé au mode détaillant.")
    current_date = datetime.now(ZoneInfo("Africa/Lubumbashi")).date()
    if balance_date > current_date:
        raise OpeningBalanceError("La date ne peut pas être dans le futur.")

    changed = []
    for network, raw_values in updates.items():
        raw_quantity, raw_unit_cost = raw_values
        if raw_quantity is None and raw_unit_cost is None:
            continue
        entry = StockOpeningBalance.query.filter_by(
            business_id=business.id,
            network=network,
            balance_date=balance_date,
        ).one_or_none()
        quantity = (
            as_decimal(raw_quantity)
            if raw_quantity is not None
            else as_decimal(entry.quantity) if entry is not None else None
        )
        if quantity is None:
            raise OpeningBalanceError(
                f"Indiquez la quantité de {network.value}."
            )
        if quantity < 0 or quantity != quantity.to_integral_value():
            raise OpeningBalanceError("Les quantités doivent être des nombres entiers positifs.")

        if quantity == 0:
            unit_cost = Decimal("0")
        elif raw_unit_cost is not None:
            unit_cost = quantize_unit_price(raw_unit_cost)
        elif entry is not None and entry.unit_cost > 0:
            unit_cost = quantize_unit_price(entry.unit_cost)
        else:
            stock = Stock.query.filter_by(
                business_id=business.id, network=network
            ).one_or_none()
            if stock is not None and stock.average_cost_per_unit > 0:
                unit_cost = quantize_unit_price(stock.average_cost_per_unit)
            else:
                raise OpeningBalanceError(
                    f"Indiquez le coût par unité de {network.value}."
                )
        if quantity > 0 and unit_cost <= 0:
            raise OpeningBalanceError("Le coût par unité doit être positif.")
        total_cost = (quantity * unit_cost).quantize(INTERNAL_MONEY_QUANTUM)
        if (
            entry is not None
            and entry.is_cost_estimated
            and raw_unit_cost is None
            and as_decimal(entry.quantity) != quantity
        ):
            raise OpeningBalanceError(
                f"Confirmez le coût par unité de {network.value}."
            )
        remains_estimated = bool(
            entry is not None and entry.is_cost_estimated and raw_unit_cost is None
        )

        is_changed = entry is None or any((
            as_decimal(entry.quantity) != quantity,
            as_decimal(entry.unit_cost) != unit_cost,
            as_decimal(entry.actual_total_cost) != total_cost,
            entry.is_cost_estimated != remains_estimated,
        ))
        if not is_changed:
            continue
        _ensure_history_is_safe(
            business_id=business.id,
            network=network,
            balance_date=balance_date,
            current_date=current_date,
        )
        if entry is None:
            entry = StockOpeningBalance(
                vendeur_id=business.owner_user_id,
                business_id=business.id,
                network=network,
                balance_date=balance_date,
            )
            db.session.add(entry)
        entry.quantity = quantity
        entry.unit_cost = unit_cost
        entry.actual_total_cost = total_cost
        entry.is_cost_estimated = remains_estimated
        entry.set_by_id = recorded_by.id
        changed.append((network, entry))

    if not changed:
        raise OpeningBalanceError("Saisissez au moins une quantité ou un coût à modifier.")
    db.session.flush()
    if balance_date == current_date:
        for network, entry in changed:
            _reconcile_today_stock(
                business=business, network=network, opening=entry
            )
    return [entry for _, entry in changed]


def _ensure_history_is_safe(
    *, business_id, network, balance_date, current_date
):
    dependent_sale = (
        db.session.query(SaleItem.id)
        .join(Sale)
        .filter(
            Sale.business_id == business_id,
            Sale.status == TransactionStatus.ACTIVE,
            SaleItem.network == network,
            Sale.sale_date >= balance_date,
        )
        .first()
    )
    if dependent_sale is not None:
        raise OpeningBalanceError(
            f"Le stock {network.value} a déjà été vendu. "
            "Le stock d'ouverture ne peut plus être modifié."
        )
    if balance_date < current_date:
        later_purchase = (
            db.session.query(StockPurchase.id)
            .join(Stock)
            .filter(
                Stock.business_id == business_id,
                StockPurchase.network == network,
                StockPurchase.status == TransactionStatus.ACTIVE,
                StockPurchase.purchase_date >= balance_date,
            )
            .first()
        )
        if later_purchase is not None:
            raise OpeningBalanceError(
                f"Le stock {network.value} a des achats plus récents. "
                "Le stock d'ouverture ne peut plus être modifié."
            )


def _reconcile_today_stock(*, business, network, opening):
    purchased_quantity, purchased_cost = (
        db.session.query(
            func.coalesce(func.sum(StockPurchase.amount_purchased), 0),
            func.coalesce(func.sum(StockPurchase.actual_total_cost), 0),
        )
        .join(Stock)
        .filter(
            Stock.business_id == business.id,
            StockPurchase.network == network,
            StockPurchase.status == TransactionStatus.ACTIVE,
            StockPurchase.purchase_date == opening.balance_date,
        )
        .one()
    )
    balance = as_decimal(opening.quantity) + as_decimal(purchased_quantity)
    inventory_value = (
        as_decimal(opening.actual_total_cost) + as_decimal(purchased_cost)
    ).quantize(INTERNAL_MONEY_QUANTUM)
    stock = Stock.query.filter_by(
        business_id=business.id, network=network
    ).with_for_update().one_or_none()
    if stock is None:
        stock = Stock(
            vendeur_id=business.owner_user_id,
            business_id=business.id,
            network=network,
            selling_price_per_unit=opening.unit_cost,
        )
        db.session.add(stock)
    stock.balance = balance
    stock.inventory_value = inventory_value
    stock.average_cost_per_unit = (
        quantize_unit_price(inventory_value / balance)
        if balance else Decimal("0")
    )
    if as_decimal(purchased_quantity) == 0 and as_decimal(opening.quantity) > 0:
        stock.buying_price_per_unit = quantize_unit_price(opening.unit_cost)

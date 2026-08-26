"""Cost-aware, business-scoped opening stock anchors."""

from decimal import Decimal

from sqlalchemy import func

from apps import db
from apps.dates import business_local_date
from apps.models import (
    BusinessApprovalStatus,
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
from apps.user_messages import user_message


class OpeningBalanceError(ValueError):
    """Raised when an opening balance would rewrite dependent history."""


def save_opening_balances(
    *, business, recorded_by, balance_date, updates, exact_totals=None
):
    """Upsert only submitted networks and reconcile today's inventory value."""
    if business.business_type not in (BusinessType.RETAIL, BusinessType.WHOLESALE):
        raise OpeningBalanceError("Ce mode ne permet pas de gérer un stock d'ouverture.")
    if (
        business.business_type == BusinessType.WHOLESALE
        and business.approval_status != BusinessApprovalStatus.APPROVED
    ):
        raise OpeningBalanceError("Le mode grossiste doit d'abord être approuvé.")
    current_date = business_local_date()
    if balance_date > current_date:
        raise OpeningBalanceError("La date ne peut pas être dans le futur.")

    exact_totals = exact_totals or {}
    changed = []
    for network, raw_values in updates.items():
        raw_quantity, raw_unit_cost = raw_values
        raw_total_cost = exact_totals.get(network)
        if (
            raw_quantity is None
            and raw_unit_cost is None
            and raw_total_cost is None
        ):
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
            if raw_total_cost is not None and as_decimal(raw_total_cost) != 0:
                raise OpeningBalanceError(
                    "Une quantité nulle doit avoir une valeur totale nulle."
                )
            unit_cost = Decimal("0")
            total_cost = Decimal("0")
        elif raw_total_cost is not None:
            total_cost = as_decimal(raw_total_cost).quantize(INTERNAL_MONEY_QUANTUM)
            if total_cost <= 0:
                raise OpeningBalanceError("La valeur totale du stock doit être positive.")
            unit_cost = quantize_unit_price(total_cost / quantity)
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
                required_value = (
                    "la valeur totale"
                    if business.business_type == BusinessType.WHOLESALE
                    else "le coût par unité"
                )
                raise OpeningBalanceError(
                    f"Indiquez {required_value} du stock {network.value}."
                )
        if quantity > 0 and unit_cost <= 0:
            raise OpeningBalanceError("Le coût par unité doit être positif.")
        if quantity > 0 and raw_total_cost is None:
            total_cost = (quantity * unit_cost).quantize(INTERNAL_MONEY_QUANTUM)
        if (
            entry is not None
            and entry.is_cost_estimated
            and raw_unit_cost is None
            and raw_total_cost is None
            and as_decimal(entry.quantity) != quantity
        ):
            required_value = (
                "la valeur totale"
                if business.business_type == BusinessType.WHOLESALE
                else "le coût réel par unité"
            )
            raise OpeningBalanceError(
                f"Indiquez {required_value} du stock {network.value} pour confirmer cette correction."
            )
        remains_estimated = bool(
            entry is not None
            and entry.is_cost_estimated
            and raw_unit_cost is None
            and raw_total_cost is None
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
        value_name = (
            "une valeur totale"
            if business.business_type == BusinessType.WHOLESALE
            else "un coût par unité"
        )
        raise OpeningBalanceError(
            f"Saisissez une quantité ou {value_name} pour au moins un réseau."
        )
    db.session.flush()
    if balance_date == current_date:
        for network, entry in changed:
            _reconcile_today_stock(
                business=business, network=network, opening=entry
            )
    return [entry for _, entry in changed]


def opening_quantity_for_date(*, business_id, network, target_date):
    """Roll an opening quantity forward from the latest dated stock anchor."""
    anchor = (
        StockOpeningBalance.query.filter(
            StockOpeningBalance.business_id == business_id,
            StockOpeningBalance.network == network,
            StockOpeningBalance.balance_date <= target_date,
        )
        .order_by(StockOpeningBalance.balance_date.desc())
        .first()
    )
    start_date = anchor.balance_date if anchor is not None else None

    purchase_filters = [
        Stock.business_id == business_id,
        StockPurchase.network == network,
        StockPurchase.purchase_date < target_date,
        StockPurchase.status == TransactionStatus.ACTIVE,
    ]
    sale_filters = [
        Sale.business_id == business_id,
        SaleItem.network == network,
        Sale.sale_date < target_date,
        Sale.status == TransactionStatus.ACTIVE,
    ]
    if start_date is not None:
        purchase_filters.append(StockPurchase.purchase_date >= start_date)
        sale_filters.append(Sale.sale_date >= start_date)

    purchased = (
        db.session.query(func.sum(StockPurchase.amount_purchased))
        .join(Stock)
        .filter(*purchase_filters)
        .scalar()
        or 0
    )
    sold = (
        db.session.query(func.sum(SaleItem.quantity))
        .join(Sale)
        .filter(*sale_filters)
        .scalar()
        or 0
    )
    opening = as_decimal(anchor.quantity) if anchor is not None else Decimal("0")
    return opening + as_decimal(purchased) - as_decimal(sold)


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
            user_message(
                f"Des ventes utilisent déjà le stock {network.value}.",
                "Corrigez ou annulez ces ventes avant de modifier l'ouverture.",
            )
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
                user_message(
                    f"Un achat {network.value} a été enregistré après cette ouverture.",
                    "Corrigez d'abord cet achat.",
                )
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

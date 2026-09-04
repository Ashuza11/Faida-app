"""Read-only wholesale reporting from immutable transaction facts."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func

from apps import db
from apps.models import (
    Business,
    BusinessType,
    CashInflow,
    CashInflowCategory,
    NetworkType,
    PaymentAllocationKind,
    Sale,
    SaleItem,
    Stock,
    StockPurchase,
    TransactionStatus,
)
from apps.opening_balances import opening_quantity_for_date
from apps.wholesale_costs import (
    sale_item_cost_anomaly_reason,
    sale_item_has_cost_anomaly,
)


ZERO = Decimal("0")


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def build_wholesale_daily_report(
    *, business: Business, target_date: date
) -> dict:
    """Build one USD daily report scoped to a single wholesale business."""
    if business.business_type != BusinessType.WHOLESALE:
        raise ValueError("Ce rapport est disponible uniquement en mode grossiste.")

    rows = {}
    for network in NetworkType:
        purchase = (
            db.session.query(
                func.sum(StockPurchase.amount_purchased).label("quantity"),
                func.sum(StockPurchase.actual_total_cost).label("cost"),
            )
            .join(Stock)
            .filter(
                Stock.business_id == business.id,
                StockPurchase.network == network,
                StockPurchase.purchase_date == target_date,
                StockPurchase.status == TransactionStatus.ACTIVE,
            )
            .one()
        )
        sold = (
            db.session.query(
                func.sum(SaleItem.quantity).label("quantity"),
                func.sum(SaleItem.subtotal).label("revenue"),
                func.sum(SaleItem.cost_total).label("cost"),
                func.sum(SaleItem.margin_amount).label("margin"),
            )
            .join(Sale)
            .filter(
                Sale.business_id == business.id,
                SaleItem.network == network,
                Sale.sale_date == target_date,
                Sale.status == TransactionStatus.ACTIVE,
            )
            .one()
        )
        opening = opening_quantity_for_date(
            business_id=business.id,
            network=network,
            target_date=target_date,
        )
        purchased_quantity = Decimal(purchase.quantity or 0)
        sold_quantity = Decimal(sold.quantity or 0)
        rows[network.name] = {
            "network": network,
            "opening": opening,
            "purchased": purchased_quantity,
            "purchase_cost": _decimal(purchase.cost),
            "sold": sold_quantity,
            "revenue": _decimal(sold.revenue),
            "cost": _decimal(sold.cost),
            "margin": _decimal(sold.margin),
            "closing": opening + purchased_quantity - sold_quantity,
        }

    price_groups = (
        db.session.query(
            SaleItem.network,
            SaleItem.price_per_unit_applied,
            func.sum(SaleItem.quantity).label("quantity"),
            func.sum(SaleItem.subtotal).label("revenue"),
            func.sum(SaleItem.cost_total).label("cost"),
            func.sum(SaleItem.margin_amount).label("margin"),
        )
        .join(Sale)
        .filter(
            Sale.business_id == business.id,
            Sale.sale_date == target_date,
            Sale.status == TransactionStatus.ACTIVE,
        )
        .group_by(SaleItem.network, SaleItem.price_per_unit_applied)
        .order_by(SaleItem.network, SaleItem.price_per_unit_applied)
        .all()
    )
    sale_items_for_day = (
        SaleItem.query.join(Sale)
        .filter(
            Sale.business_id == business.id,
            Sale.sale_date == target_date,
            Sale.status == TransactionStatus.ACTIVE,
        )
        .all()
    )
    anomalous_sale_items = [
        item for item in sale_items_for_day if sale_item_has_cost_anomaly(item)
    ]

    inflows = CashInflow.query.filter_by(
        business_id=business.id,
        payment_date=target_date,
        category=CashInflowCategory.SALE_COLLECTION,
        status=TransactionStatus.ACTIVE,
    ).all()
    cash_collected = sum((_decimal(inflow.amount) for inflow in inflows), ZERO)
    old_debt_collected = sum(
        (
            _decimal(inflow.amount)
            for inflow in inflows
            if inflow.allocation_kind == PaymentAllocationKind.PRIOR_DEBT
        ),
        ZERO,
    )
    collected_margin = ZERO
    anomalous_collection_sale_ids = set()
    anomalous_collection_items = {}
    for inflow in inflows:
        if inflow.sale and inflow.sale.total_amount_due:
            unsafe_items = [
                item for item in inflow.sale.sale_items
                if sale_item_has_cost_anomaly(item)
            ]
            if unsafe_items:
                anomalous_collection_sale_ids.add(inflow.sale.id)
                anomalous_collection_items.update({
                    item.id: item for item in unsafe_items
                })
                continue
            sale_margin = sum(
                (_decimal(item.margin_amount) for item in inflow.sale.sale_items), ZERO
            )
            collected_margin += (
                _decimal(inflow.amount)
                * sale_margin
                / _decimal(inflow.sale.total_amount_due)
            )

    sales_for_day = Sale.query.filter_by(
        business_id=business.id,
        sale_date=target_date,
        status=TransactionStatus.ACTIVE,
    ).all()
    new_debt = sum(
        (
            _decimal(sale.total_amount_due) - _decimal(sale.initial_cash_paid)
            for sale in sales_for_day
        ),
        ZERO,
    )
    debt_created_to_date = (
        db.session.query(
            func.sum(Sale.total_amount_due - Sale.initial_cash_paid)
        )
        .filter(
            Sale.business_id == business.id,
            Sale.sale_date <= target_date,
            Sale.status == TransactionStatus.ACTIVE,
        )
        .scalar()
        or ZERO
    )
    debt_collected_to_date = (
        db.session.query(func.sum(CashInflow.amount))
        .filter(
            CashInflow.business_id == business.id,
            CashInflow.payment_date <= target_date,
            CashInflow.allocation_kind == PaymentAllocationKind.PRIOR_DEBT,
            CashInflow.status == TransactionStatus.ACTIVE,
        )
        .scalar()
        or ZERO
    )

    sale_item_ids_for_day = {item.id for item in anomalous_sale_items}
    anomaly_items = {
        item.id: item for item in anomalous_sale_items
    }
    anomaly_items.update(anomalous_collection_items)
    anomaly_details = []
    for item in sorted(
        anomaly_items.values(),
        key=lambda value: (value.sale.sale_date, value.sale_id, value.id),
    ):
        reason = sale_item_cost_anomaly_reason(item)
        anomaly_details.append({
            "sale_item_id": item.id,
            "sale_id": item.sale_id,
            "sale_date": item.sale.sale_date,
            "client_id": item.sale.client_id,
            "client_name": item.sale.client_display_name,
            "network": item.network,
            "reason_code": reason["code"],
            "reason": reason["label"],
            "affects_sales_margin": item.id in sale_item_ids_for_day,
            "affects_collected_margin": item.id in anomalous_collection_items,
        })

    totals = {
        "purchased": sum((row["purchased"] for row in rows.values()), ZERO),
        "purchase_cost": sum((row["purchase_cost"] for row in rows.values()), ZERO),
        "sold": sum((row["sold"] for row in rows.values()), ZERO),
        "revenue": sum((row["revenue"] for row in rows.values()), ZERO),
        "cost": sum((row["cost"] for row in rows.values()), ZERO),
        "sales_margin": sum((row["margin"] for row in rows.values()), ZERO),
        "cash_collected": cash_collected,
        "collected_margin": collected_margin,
        "new_debt": new_debt,
        "old_debt_collected": old_debt_collected,
        "remaining_debt": _decimal(debt_created_to_date)
        - _decimal(debt_collected_to_date),
        "sales_margin_has_anomaly": bool(anomalous_sale_items),
        "collected_margin_has_anomaly": bool(anomalous_collection_sale_ids),
    }
    return {
        "date": target_date,
        "currency": business.currency_code,
        "networks": rows,
        "price_groups": price_groups,
        "totals": totals,
        "cost_anomalies": {
            "sale_item_ids": [item.id for item in anomalous_sale_items],
            "sale_ids": sorted({item.sale_id for item in anomalous_sale_items}),
            "networks": sorted({item.network.name for item in anomalous_sale_items}),
            "collection_sale_ids": sorted(anomalous_collection_sale_ids),
            "all_sale_ids": sorted({detail["sale_id"] for detail in anomaly_details}),
            "details": anomaly_details,
        },
    }

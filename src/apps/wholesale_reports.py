"""Read-only wholesale reporting from immutable transaction facts."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import selectinload

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


def build_wholesale_dashboard_summary(
    *, business: Business, target_date: date
) -> dict:
    """Return the small set of daily cash metrics needed by the home screen."""
    if business.business_type != BusinessType.WHOLESALE:
        raise ValueError("Ce résumé est disponible uniquement en mode grossiste.")

    sales = (
        db.session.query(
            func.sum(Sale.total_amount_due).label("revenue"),
            func.sum(Sale.debt_amount).label("debt"),
        )
        .filter(
            Sale.business_id == business.id,
            Sale.sale_date == target_date,
            Sale.status == TransactionStatus.ACTIVE,
        )
        .one()
    )
    cash_collected = (
        db.session.query(func.sum(CashInflow.amount))
        .filter(
            CashInflow.business_id == business.id,
            CashInflow.payment_date == target_date,
            CashInflow.category == CashInflowCategory.SALE_COLLECTION,
            CashInflow.status == TransactionStatus.ACTIVE,
        )
        .scalar()
    )
    return {
        "sales": _decimal(sales.revenue),
        "debt": _decimal(sales.debt),
        "cash_collected": _decimal(cash_collected),
    }


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
                func.sum(
                    SaleItem.quantity * SaleItem.price_per_unit_applied
                ).label("raw_revenue"),
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
        revenue = _decimal(sold.revenue)
        raw_revenue = _decimal(sold.raw_revenue)
        cost = _decimal(sold.cost)
        rows[network.name] = {
            "network": network,
            "opening": opening,
            "purchased": purchased_quantity,
            "purchase_cost": _decimal(purchase.cost),
            "sold": sold_quantity,
            "revenue": revenue,
            "raw_revenue": raw_revenue,
            "cost": cost,
            "margin": _decimal(sold.margin),
            "commercial_margin": raw_revenue - cost,
            "rounding_adjustment": revenue - raw_revenue,
            "average_selling_price": (
                raw_revenue / sold_quantity if sold_quantity else ZERO
            ),
            "average_cost_per_unit": (
                cost / sold_quantity if sold_quantity else ZERO
            ),
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
    current_sale_cash_collected = ZERO
    old_debt_collected = ZERO
    unclassified_cash_collected = ZERO
    collected_margin = ZERO
    collected_commercial_margin = ZERO
    collected_rounding_adjustment = ZERO
    current_sale_collected_margin = ZERO
    prior_debt_collected_margin = ZERO
    unclassified_collected_margin = ZERO
    anomalous_collection_sale_ids = set()
    anomalous_collection_items = {}
    for inflow in inflows:
        inflow_amount = _decimal(inflow.amount)
        if inflow.allocation_kind == PaymentAllocationKind.CURRENT_SALE:
            current_sale_cash_collected += inflow_amount
        elif inflow.allocation_kind == PaymentAllocationKind.PRIOR_DEBT:
            old_debt_collected += inflow_amount
        else:
            unclassified_cash_collected += inflow_amount
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
            sale_raw_revenue = sum(
                (
                    _decimal(item.quantity)
                    * _decimal(item.price_per_unit_applied)
                    for item in inflow.sale.sale_items
                ),
                ZERO,
            )
            sale_cost = sum(
                (_decimal(item.cost_total) for item in inflow.sale.sale_items), ZERO
            )
            sale_commercial_margin = sale_raw_revenue - sale_cost
            sale_rounding_adjustment = (
                _decimal(inflow.sale.total_amount_due) - sale_raw_revenue
            )
            allocation_ratio = (
                inflow_amount / _decimal(inflow.sale.total_amount_due)
            )
            allocated_margin = (
                allocation_ratio * sale_margin
            )
            collected_margin += allocated_margin
            collected_commercial_margin += (
                allocation_ratio * sale_commercial_margin
            )
            collected_rounding_adjustment += (
                allocation_ratio * sale_rounding_adjustment
            )
            if inflow.allocation_kind == PaymentAllocationKind.CURRENT_SALE:
                current_sale_collected_margin += allocated_margin
            elif inflow.allocation_kind == PaymentAllocationKind.PRIOR_DEBT:
                prior_debt_collected_margin += allocated_margin
            else:
                unclassified_collected_margin += allocated_margin

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
    debt_created_before_date = (
        db.session.query(
            func.sum(Sale.total_amount_due - Sale.initial_cash_paid)
        )
        .filter(
            Sale.business_id == business.id,
            Sale.sale_date < target_date,
            Sale.status == TransactionStatus.ACTIVE,
        )
        .scalar()
        or ZERO
    )
    debt_collected_before_date = (
        db.session.query(func.sum(CashInflow.amount))
        .filter(
            CashInflow.business_id == business.id,
            CashInflow.payment_date < target_date,
            CashInflow.allocation_kind == PaymentAllocationKind.PRIOR_DEBT,
            CashInflow.status == TransactionStatus.ACTIVE,
        )
        .scalar()
        or ZERO
    )
    opening_debt = (
        _decimal(debt_created_before_date)
        - _decimal(debt_collected_before_date)
    )
    prior_day_debt_collected = sum(
        (
            _decimal(inflow.amount)
            for inflow in inflows
            if inflow.allocation_kind == PaymentAllocationKind.PRIOR_DEBT
            and inflow.sale is not None
            and inflow.sale.sale_date < target_date
        ),
        ZERO,
    )
    same_day_debt_collected = sum(
        (
            _decimal(inflow.amount)
            for inflow in inflows
            if inflow.allocation_kind == PaymentAllocationKind.PRIOR_DEBT
            and inflow.sale is not None
            and inflow.sale.sale_date == target_date
        ),
        ZERO,
    )
    unclassified_debt_collected = (
        old_debt_collected
        - prior_day_debt_collected
        - same_day_debt_collected
    )

    debt_allocations = dict(
        db.session.query(
            CashInflow.sale_id,
            func.sum(CashInflow.amount),
        )
        .filter(
            CashInflow.business_id == business.id,
            CashInflow.payment_date <= target_date,
            CashInflow.allocation_kind == PaymentAllocationKind.PRIOR_DEBT,
            CashInflow.status == TransactionStatus.ACTIVE,
            CashInflow.sale_id.is_not(None),
        )
        .group_by(CashInflow.sale_id)
        .all()
    )
    debt_by_client = {}
    debt_sales = (
        Sale.query.options(selectinload(Sale.client))
        .filter(
            Sale.business_id == business.id,
            Sale.sale_date <= target_date,
            Sale.status == TransactionStatus.ACTIVE,
        )
        .all()
    )
    for sale in debt_sales:
        balance = (
            _decimal(sale.total_amount_due)
            - _decimal(sale.initial_cash_paid)
            - _decimal(debt_allocations.get(sale.id))
        )
        if balance <= ZERO:
            continue
        key = sale.customer_group_key
        client_debt = debt_by_client.setdefault(key, {
            "client_id": sale.client_id,
            "client_name": sale.client_display_name,
            "amount": ZERO,
        })
        client_debt["amount"] += balance
    client_debts = sorted(
        debt_by_client.values(),
        key=lambda item: (-item["amount"], item["client_name"].casefold()),
    )
    client_debt_total = sum(
        (item["amount"] for item in client_debts), ZERO
    )
    remaining_debt = (
        _decimal(debt_created_to_date) - _decimal(debt_collected_to_date)
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
        "commercial_margin": sum(
            (row["commercial_margin"] for row in rows.values()), ZERO
        ),
        "rounding_adjustment": sum(
            (row["rounding_adjustment"] for row in rows.values()), ZERO
        ),
        "cash_collected": cash_collected,
        "collected_margin": collected_margin,
        "collected_commercial_margin": collected_commercial_margin,
        "collected_rounding_adjustment": collected_rounding_adjustment,
        "current_sale_cash_collected": current_sale_cash_collected,
        "prior_debt_cash_collected": old_debt_collected,
        "unclassified_cash_collected": unclassified_cash_collected,
        "current_sale_collected_margin": current_sale_collected_margin,
        "prior_debt_collected_margin": prior_debt_collected_margin,
        "unclassified_collected_margin": unclassified_collected_margin,
        "new_debt": new_debt,
        "opening_debt": opening_debt,
        "old_debt_collected": old_debt_collected,
        "prior_day_debt_collected": prior_day_debt_collected,
        "same_day_debt_collected": same_day_debt_collected,
        "unclassified_debt_collected": unclassified_debt_collected,
        "remaining_debt": remaining_debt,
        "client_debt_total": client_debt_total,
        "debt_reconciliation_difference": remaining_debt - client_debt_total,
        "sales_margin_has_anomaly": bool(anomalous_sale_items),
        "collected_margin_has_anomaly": bool(anomalous_collection_sale_ids),
    }
    return {
        "date": target_date,
        "currency": business.currency_code,
        "networks": rows,
        "price_groups": price_groups,
        "client_debts": client_debts,
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

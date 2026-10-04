"""Canonical financial reporting for retail sales.

Retail invoices are rounded once to the nearest configured FC amount while
sale-item costs retain higher precision.  This module reconciles those two
facts so every report uses the amount the customer actually owes without
hiding the effect of invoice rounding.
"""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import selectinload

from apps.models import NetworkType, Sale, TransactionStatus


ZERO = Decimal("0")


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def build_retail_margin_report(*, business_id: int | None, target_date, vendeur_id=None):
    """Return reconciled retail revenue, cost, margin, and cost-quality data."""
    query = Sale.query.options(
        selectinload(Sale.sale_items), selectinload(Sale.client)
    ).filter(
        Sale.sale_date == target_date,
        Sale.status == TransactionStatus.ACTIVE,
    )
    query = (
        query.filter(Sale.business_id == business_id)
        if business_id is not None
        else query.filter(Sale.vendeur_id == vendeur_id)
    )
    sales = (
        query
        .order_by(Sale.created_at, Sale.id)
        .all()
    )

    network_rows = {
        network.name: {
            "network": network,
            "qty": 0,
            "raw_revenue": ZERO,
            "revenue": ZERO,
            "cost": ZERO,
            "commercial_margin": ZERO,
            "rounding_adjustment": ZERO,
            "profit": ZERO,
            "buying_price": ZERO,
            "has_estimated_cost": False,
        }
        for network in NetworkType
    }
    price_rows = defaultdict(lambda: {
        "qty": 0,
        "raw_revenue": ZERO,
        "revenue": ZERO,
        "cost": ZERO,
        "commercial_margin": ZERO,
        "rounding_adjustment": ZERO,
        "margin": ZERO,
        "has_estimated_cost": False,
    })
    losses = []
    estimated_sales = {}

    for sale in sales:
        items = sorted(sale.sale_items, key=lambda item: item.id or 0)
        if not items:
            continue
        line_total = sum((_decimal(item.subtotal) for item in items), ZERO)
        invoice_adjustment = _decimal(sale.total_amount_due) - line_total

        allocated_adjustments = []
        allocated_total = ZERO
        for index, item in enumerate(items):
            if index == len(items) - 1:
                adjustment = invoice_adjustment - allocated_total
            elif line_total:
                adjustment = (
                    invoice_adjustment * _decimal(item.subtotal) / line_total
                ).quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP)
            else:
                adjustment = ZERO
            allocated_adjustments.append(adjustment)
            allocated_total += adjustment

        for index, item in enumerate(items):
            raw_revenue = _decimal(item.quantity) * _decimal(
                item.price_per_unit_applied
            )
            line_revenue = _decimal(item.subtotal)
            allocated_invoice_adjustment = allocated_adjustments[index]
            recognized_revenue = line_revenue + allocated_invoice_adjustment
            rounding_adjustment = recognized_revenue - raw_revenue
            cost = _decimal(item.cost_total)
            commercial_margin = raw_revenue - cost
            final_margin = recognized_revenue - cost
            estimated = bool(item.is_cost_estimated)

            network_row = network_rows[item.network.name]
            network_row["qty"] += int(item.quantity)
            network_row["raw_revenue"] += raw_revenue
            network_row["revenue"] += recognized_revenue
            network_row["cost"] += cost
            network_row["commercial_margin"] += commercial_margin
            network_row["rounding_adjustment"] += rounding_adjustment
            network_row["profit"] += final_margin
            network_row["has_estimated_cost"] |= estimated

            key = (item.network.name, _decimal(item.price_per_unit_applied))
            price_row = price_rows[key]
            price_row["qty"] += int(item.quantity)
            price_row["raw_revenue"] += raw_revenue
            price_row["revenue"] += recognized_revenue
            price_row["cost"] += cost
            price_row["commercial_margin"] += commercial_margin
            price_row["rounding_adjustment"] += rounding_adjustment
            price_row["margin"] += final_margin
            price_row["has_estimated_cost"] |= estimated

            if estimated:
                estimated_sales[sale.id] = {
                    "sale_id": sale.id,
                    "client": sale.client_display_name,
                    "date": sale.sale_date,
                }
            elif commercial_margin < 0:
                losses.append({
                    "sale_id": sale.id,
                    "client": sale.client_display_name,
                    "date": sale.sale_date,
                    "network": item.network,
                    "quantity": int(item.quantity),
                    "selling_price": _decimal(item.price_per_unit_applied),
                    "cost_price": _decimal(item.cost_per_unit_snapshot),
                    "loss": -commercial_margin,
                })

    price_breakdown = defaultdict(list)
    for (network_name, price), values in sorted(
        price_rows.items(), key=lambda row: (row[0][0], row[0][1])
    ):
        price_breakdown[network_name].append({"price": price, **values})

    totals = {
        "qty": 0,
        "raw_revenue": ZERO,
        "revenue": ZERO,
        "cost": ZERO,
        "commercial_margin": ZERO,
        "rounding_adjustment": ZERO,
        "profit": ZERO,
        "has_estimated_cost": False,
    }
    for row in network_rows.values():
        row["buying_price"] = (
            row["cost"] / Decimal(row["qty"]) if row["qty"] else ZERO
        )
        for field in (
            "qty", "raw_revenue", "revenue", "cost", "commercial_margin",
            "rounding_adjustment", "profit",
        ):
            totals[field] += row[field]
        totals["has_estimated_cost"] |= row["has_estimated_cost"]

    # This invariant is the central reason this builder exists.
    invoice_total = sum((_decimal(sale.total_amount_due) for sale in sales), ZERO)
    if totals["revenue"] != invoice_total:
        raise RuntimeError("Le rapport des ventes ne correspond pas aux factures.")

    return {
        "sales": sales,
        "networks": network_rows,
        "price_breakdown": dict(price_breakdown),
        "totals": totals,
        "losses": losses,
        "estimated_sales": list(estimated_sales.values()),
    }

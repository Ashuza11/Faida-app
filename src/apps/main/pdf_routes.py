# ============================================================
# PDF DOWNLOAD ROUTE
# ============================================================

from flask import Blueprint, send_file, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from decimal import Decimal

from apps.decorators import get_current_vendeur_id, vendeur_required
from apps.main.utils import (
    get_date_context,
    get_daily_report_data,
    get_stock_purchase_history_query,
    get_sales_history_query,
)
from apps.models import (
    NetworkType, DailyOverallReport, DailyStockReport,
    Stock, Sale, SaleItem, Client,
)
from apps.main.pdf_utils import generate_daily_report_pdf
from apps import db
from sqlalchemy import func

# Create a NEW blueprint for PDF routes
pdf_bp = Blueprint('pdf_bp', __name__)


@pdf_bp.route("/rapports/download", methods=["GET"])
@login_required
@vendeur_required
def download_report_pdf():
    """
    Generate and download the daily report as a PDF.
    Uses the same date parameter as the main rapports route.
    """

    # --- 1. Get Date Context ---
    ctx = get_date_context()

    # --- 2. Get Business Name ---
    if current_user.is_platform_admin:
        business_name = "Faida App - Rapport Global"
    else:
        business_name = current_user.username

    # --- 3. Get Vendeur ID for filtering ---
    vendeur_id = get_current_vendeur_id()
    target_date = ctx['selected_date']

    # --- 4. Initialize Stock Balance Structures ---
    networks = list(NetworkType.__members__.values())

    def zero_money():
        return Decimal("0.00")

    report_data = {
        network.name: {
            "initial_stock": zero_money(),
            "purchased_stock": zero_money(),
            "sold_stock": zero_money(),
            "final_stock": zero_money(),
            "virtual_value": zero_money(),
            "debt_amount": zero_money(),
        } for network in networks
    }

    grand_totals = {
        "initial_stock": zero_money(),
        "purchased_stock": zero_money(),
        "sold_stock": zero_money(),
        "final_stock": zero_money(),
        "virtual_value": zero_money(),
        "total_debts": zero_money(),
        "total_calculated_sold_stock": zero_money(),
    }

    # --- 5. Fetch Stock Balance Data (same logic as rapports route) ---
    if ctx['is_today']:
        calculated_data, _, total_live_debts = get_daily_report_data(
            current_app,
            target_date,
            start_of_utc_range=ctx['start_utc'],
            end_of_utc_range=ctx['end_utc'],
            vendeur_id=vendeur_id,
        )
        for network_name, data in calculated_data.items():
            report_data[network_name].update({
                "initial_stock": data["initial_stock"],
                "purchased_stock": data["purchased_stock"],
                "sold_stock": data["sold_stock_quantity"],
                "final_stock": data["final_stock"],
                "virtual_value": data["virtual_value"],
                "debt_amount": data.get("debt_amount", zero_money()),
            })
            grand_totals["initial_stock"] += data["initial_stock"]
            grand_totals["purchased_stock"] += data["purchased_stock"]
            grand_totals["sold_stock"] += data["sold_stock_quantity"]
            grand_totals["final_stock"] += data["final_stock"]
            grand_totals["virtual_value"] += data["virtual_value"]
        grand_totals["total_debts"] = total_live_debts or zero_money()
    else:
        query_filter = {"report_date": target_date}
        if vendeur_id:
            query_filter["vendeur_id"] = vendeur_id

        overall_report = DailyOverallReport.query.filter_by(**query_filter).first()
        if overall_report:
            grand_totals.update({
                "initial_stock": overall_report.total_initial_stock,
                "purchased_stock": overall_report.total_purchased_stock,
                "sold_stock": overall_report.total_sold_stock,
                "final_stock": overall_report.total_final_stock,
                "virtual_value": overall_report.total_virtual_value,
                "total_debts": overall_report.total_debts,
            })
            for r in DailyStockReport.query.filter_by(**query_filter).all():
                if r.network.name in report_data:
                    report_data[r.network.name].update({
                        "initial_stock": r.initial_stock_balance,
                        "purchased_stock": r.purchased_stock_amount,
                        "sold_stock": r.sold_stock_amount,
                        "final_stock": r.final_stock_balance,
                        "virtual_value": r.virtual_value,
                        "debt_amount": r.debt_amount,
                    })

    grand_totals["total_calculated_sold_stock"] = (
        grand_totals["initial_stock"]
        + grand_totals["purchased_stock"]
        - grand_totals["final_stock"]
    )

    # --- 6. Profit / Price-breakdown data ---
    stock_items = Stock.query.filter_by(vendeur_id=vendeur_id).all() if vendeur_id else []
    buying_price_map = {s.network: s.buying_price_per_unit for s in stock_items}

    pb_q = (
        db.session.query(
            SaleItem.network,
            SaleItem.price_per_unit_applied,
            func.sum(SaleItem.quantity).label('qty'),
            func.sum(SaleItem.subtotal).label('revenue'),
        )
        .join(Sale)
        .filter(Sale.sale_date == target_date)
    )
    if vendeur_id:
        pb_q = pb_q.filter(Sale.vendeur_id == vendeur_id)
    price_breakdown_rows = pb_q.group_by(
        SaleItem.network, SaleItem.price_per_unit_applied
    ).order_by(SaleItem.network, SaleItem.price_per_unit_applied).all()

    price_breakdown = {}
    for row in price_breakdown_rows:
        key = row.network.name
        if key not in price_breakdown:
            price_breakdown[key] = []
        price_breakdown[key].append({
            "price": Decimal(str(row.price_per_unit_applied)),
            "qty": int(row.qty or 0),
            "revenue": Decimal(str(row.revenue or 0)),
        })

    profit_data = {}
    grand_profit = zero_money()
    grand_revenue = zero_money()
    grand_cost = zero_money()
    for network in networks:
        entries = price_breakdown.get(network.name, [])
        total_qty = sum(e["qty"] for e in entries)
        total_revenue = sum(e["revenue"] for e in entries)
        buying_price = buying_price_map.get(network, Decimal("0.94"))
        total_cost = Decimal(str(total_qty)) * buying_price
        profit = total_revenue - total_cost
        profit_data[network.name] = {
            "network": network,
            "qty": total_qty,
            "revenue": total_revenue,
            "cost": total_cost,
            "profit": profit,
            "buying_price": buying_price,
        }
        grand_revenue += total_revenue
        grand_cost += total_cost
        grand_profit += profit

    # --- 7. Cash summary ---
    cash_q = db.session.query(
        func.sum(Sale.cash_paid).label('cash'),
        func.sum(Sale.debt_amount).label('credit'),
        func.sum(Sale.total_amount_due).label('total'),
        func.count(Sale.id).label('count'),
    ).filter(Sale.sale_date == target_date)
    if vendeur_id:
        cash_q = cash_q.filter(Sale.vendeur_id == vendeur_id)
    cash_row = cash_q.first()
    cash_summary = {
        "cash": Decimal(str(cash_row.cash or 0)),
        "credit": Decimal(str(cash_row.credit or 0)),
        "total": Decimal(str(cash_row.total or 0)),
        "count": int(cash_row.count or 0),
    }

    # --- 8. Debts today ---
    debts_q = Sale.query.filter(Sale.sale_date == target_date, Sale.debt_amount > 0)
    if vendeur_id:
        debts_q = debts_q.filter(Sale.vendeur_id == vendeur_id)
    debts_today = debts_q.order_by(Sale.debt_amount.desc()).all()

    # --- 9. All stock purchases for the date ---
    purchase_query, _ = get_stock_purchase_history_query(date_filter=True)
    all_purchases = purchase_query.all()

    # --- 10. Sales history (all, not limited to 10 for PDF) ---
    sales_q, _ = get_sales_history_query(date_filter=True)
    sales_today = sales_q.all()

    # --- 11. Generate PDF ---
    try:
        pdf_buffer = generate_daily_report_pdf(
            report_data=report_data,
            grand_totals=grand_totals,
            selected_date=ctx['date_str'],
            business_name=business_name,
            networks=networks,
            # New financial sections
            cash_summary=cash_summary,
            profit_data=profit_data,
            price_breakdown=price_breakdown,
            grand_profit=grand_profit,
            grand_revenue=grand_revenue,
            grand_cost=grand_cost,
            debts_today=debts_today,
            all_purchases=all_purchases,
            sales_today=sales_today,
        )

        filename = f"rapport_{ctx['date_str']}_{business_name.replace(' ', '_')}.pdf"
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename,
        )

    except Exception as e:
        current_app.logger.error(f"Error generating PDF: {e}", exc_info=True)
        flash("Erreur lors de la génération du PDF.", "danger")
        return redirect(url_for('main_bp.rapports', date=ctx['date_str']))

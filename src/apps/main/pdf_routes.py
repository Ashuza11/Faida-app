# ============================================================
# PDF DOWNLOAD ROUTE
# ============================================================

from flask import Blueprint, send_file, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from decimal import Decimal


from apps.decorators import get_current_vendeur_id, vendeur_required
from apps.main.utils import get_date_context, get_daily_report_data
from apps.models import NetworkType, DailyOverallReport, DailyStockReport
from apps.main.pdf_utils import generate_daily_report_pdf

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
    # For vendeur: use their username/business name
    # For platform admin: use generic name
    if current_user.is_platform_admin:
        business_name = "Faida App - Rapport Global"
    else:
        business_name = current_user.username

    # --- 3. Get Vendeur ID for filtering ---
    vendeur_id = get_current_vendeur_id()

    # --- 4. Initialize Data Structures ---
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
        "total_calculated_sold_stock": zero_money()
    }

    # --- 5. Fetch Data (same logic as rapports route) ---

    if ctx['is_today']:
        # LIVE REPORT
        calculated_data, total_sales_val, total_live_debts = get_daily_report_data(
            current_app,
            ctx['selected_date'],
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
        # HISTORICAL REPORT
        query_filter = {"report_date": ctx['selected_date']}
        if vendeur_id:
            query_filter["vendeur_id"] = vendeur_id

        overall_report = DailyOverallReport.query.filter_by(
            **query_filter).first()

        if overall_report:
            grand_totals["initial_stock"] = overall_report.total_initial_stock
            grand_totals["purchased_stock"] = overall_report.total_purchased_stock
            grand_totals["sold_stock"] = overall_report.total_sold_stock
            grand_totals["final_stock"] = overall_report.total_final_stock
            grand_totals["virtual_value"] = overall_report.total_virtual_value
            grand_totals["total_debts"] = overall_report.total_debts

            daily_network_reports = DailyStockReport.query.filter_by(
                **query_filter).all()

            for r in daily_network_reports:
                if r.network.name in report_data:
                    report_data[r.network.name].update({
                        "initial_stock": r.initial_stock_balance,
                        "purchased_stock": r.purchased_stock_amount,
                        "sold_stock": r.sold_stock_amount,
                        "final_stock": r.final_stock_balance,
                        "virtual_value": r.virtual_value,
                        "debt_amount": r.debt_amount,
                    })

    # Calculate derived total
    grand_totals["total_calculated_sold_stock"] = (
        grand_totals["initial_stock"]
        + grand_totals["purchased_stock"]
        - grand_totals["final_stock"]
    )

    # --- 6. Generate PDF ---
    try:
        from apps.main.pdf_routes import generate_daily_report_pdf

        pdf_buffer = generate_daily_report_pdf(
            report_data=report_data,
            grand_totals=grand_totals,
            selected_date=ctx['date_str'],
            business_name=business_name,
            networks=networks
        )

        # --- 7. Send File ---
        filename = f"rapport_{ctx['date_str']}_{business_name.replace(' ', '_')}.pdf"

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        current_app.logger.error(f"Error generating PDF: {e}", exc_info=True)
        flash("Erreur lors de la génération du PDF.", "danger")
        return redirect(url_for('main_bp.rapports', date=ctx['date_str']))

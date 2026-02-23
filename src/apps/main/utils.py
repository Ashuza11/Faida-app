import json
import os
from pathlib import Path
from decimal import Decimal
from apps import db
from flask import current_app, request, url_for
from apps.decorators import filter_by_vendeur, get_current_vendeur_id
from apps.decorators import filter_by_vendeur
from apps.models import (
    DailyStockReport,
    NetworkType,
    Stock,
    StockPurchase,
    Sale,
    SaleItem,
    DailyOverallReport,
)
from decimal import Decimal, ROUND_UP, getcontext
from datetime import date, datetime, timedelta, time
import pytz
from sqlalchemy import func

# Define the path to your seed data file
SEED_DATA_PATH = Path(os.getcwd()) / "apps" / "data" / "seed_data.json"

# Set precision for Decimal operations
getcontext().prec = 10


def initialize_stock_items(app):
    """
    DEPRECATED — single-tenant legacy function. Do not use.
    Stock is now created per-vendeur via create_stock_for_vendeur() in models.py,
    called automatically when a vendeur registers.
    """
    raise RuntimeError(
        "initialize_stock_items() is deprecated. "
        "Use create_stock_for_vendeur(vendeur_id) from models.py instead."
    )


def custom_round_up(amount: Decimal) -> Decimal:
    """
    Rounds a Decimal amount based on its last two digits for whole numbers (FC).

    Examples:
    - 6924.00 -> 6900.00 (xx.01 to xx.24 rounds down to xx.00)
    - 6925.00 -> 6950.00 (xx.25 to xx.49 rounds up to xx.50)
    - 6949.00 -> 6950.00
    - 6950.00 -> 6950.00 (remains xx.50)
    - 6951.00 -> 7000.00 (xx.51 to xx.99 rounds up to xx.100)
    - 6975.00 -> 7000.00
    - 6999.00 -> 7000.00
    - 6900.00 -> 6900.00 (xx.00 remains xx.00)
    """
    # Ensure amount is a Decimal
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))

    # Calculate the remainder when divided by 100
    remainder = amount % 100

    if remainder == Decimal("0"):
        return amount  # xx.00 remains xx.00
    elif Decimal("1") <= remainder <= Decimal("24"):
        # xx.01 to xx.24 rounds DOWN to xx.00
        return amount - remainder
    elif Decimal("25") <= remainder <= Decimal("50"):
        # xx.25 to xx.50 rounds UP to xx.50
        return (amount - remainder) + Decimal("50")
    elif Decimal("51") <= remainder <= Decimal("99"):
        # xx.51 to xx.99 rounds UP to xx.100 (next whole hundred)
        return (amount - remainder) + Decimal("100")
    else:
        # This case should ideally not be reached if remainder is always 0-99
        return amount


# Define the application's timezone once
APP_TIMEZONE = pytz.timezone("Africa/Lubumbashi")


def get_local_timezone_datetime_info():
    """
    Returns a tuple containing:
    (local_now: datetime,
     today_local_date: date,
     start_of_local_day_utc: datetime,
     end_of_local_day_utc: datetime)

    These represent the current time in the app's local timezone,
    the current local date, and the corresponding UTC start and end
    datetimes for that local date.
    """
    utc_now = datetime.utcnow()
    local_now = utc_now.astimezone(APP_TIMEZONE)
    today_local_date = local_now.date()

    # Calculate start and end of the local day in UTC
    start_of_local_day_dt = datetime(
        today_local_date.year, today_local_date.month, today_local_date.day, 0, 0, 0
    )
    start_of_local_day_utc = APP_TIMEZONE.localize(start_of_local_day_dt).astimezone(
        pytz.utc
    )

    end_of_local_day_dt = datetime(
        today_local_date.year,
        today_local_date.month,
        today_local_date.day,
        23,
        59,
        59,
        999999,
    )
    end_of_local_day_utc = APP_TIMEZONE.localize(end_of_local_day_dt).astimezone(
        pytz.utc
    )

    return local_now, today_local_date, start_of_local_day_utc, end_of_local_day_utc


# Helper function for parsing date parameters (from your blueprint.route)
def parse_date_param(date_str, default_date):
    """
    Safely parses a date string (YYYY-MM-DD) from the URL.
    Returns default_date if string is None or invalid.
    """
    if not date_str:
        return default_date
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        current_app.logger.warning(
            f"Invalid date format received: {date_str}. Using default."
        )
        return default_date


def get_utc_range_for_date(target_date):
    """
    Takes a date object (e.g., 2023-10-25) and returns the 
    UTC start and end datetimes for that full day in the APP_TIMEZONE.
    """
    # 1. Create midnight (00:00:00) and end-of-day (23:59:59) in LOCAL time
    start_local = datetime.combine(target_date, time.min)  # 00:00:00
    end_local = datetime.combine(target_date, time.max)   # 23:59:59.999999

    # 2. Attach the App's Timezone (Lubumbashi)
    # is_dst=None lets pytz handle daylight savings usage automatically if applicable
    start_aware = APP_TIMEZONE.localize(start_local, is_dst=None)
    end_aware = APP_TIMEZONE.localize(end_local, is_dst=None)

    # 3. Convert to UTC
    start_utc = start_aware.astimezone(pytz.utc)
    end_utc = end_aware.astimezone(pytz.utc)

    return start_utc, end_utc


def get_date_context(arg_key='date'):
    """
    Standardizes date handling across all endpoints.

    Usage:
        ctx = get_date_context()
        print(ctx['selected_date']) # Date object
        print(ctx['start_utc'])     # Datetime object (UTC)
    """
    # 1. Get "Now" Context (Environment Info) using your existing function
    _, today_local, today_start_utc, today_end_utc = get_local_timezone_datetime_info()

    # 2. Parse the requested date from URL
    date_str = request.args.get(arg_key)
    selected_date = parse_date_param(date_str, default_date=today_local)

    # 3. Determine if it is "Today"
    is_today = (selected_date == today_local)

    # 4. Calculate UTC Ranges
    if is_today:
        # Optimization: We already calculated today's range in step 1
        start_utc = today_start_utc
        end_utc = today_end_utc
    else:
        # Use our new helper for past/future dates
        start_utc, end_utc = get_utc_range_for_date(selected_date)

    return {
        "selected_date": selected_date,
        "date_str": selected_date.strftime("%Y-%m-%d"),
        "is_today": is_today,
        "start_utc": start_utc,
        "end_utc": end_utc
    }


def get_paginated_results(base_query, endpoint_name, per_page_config_key, **extra_args):
    """
    Handles standard pagination logic for any SQLAlchemy query.

    Args:
        base_query (Query): The SQLAlchemy query object (e.g., Sale.query.filter(...)).
        endpoint_name (str): The blueprint/view function name (e.g., 'main_bp.vente_stock').
        per_page_config_key (str): The configuration key for items per page (e.g., 'SALES_PER_PAGE').
        **extra_args: Any additional URL query parameters to pass through (e.g., date='2025-12-14').

    Returns:
        tuple: (pagination_object, next_url, prev_url)
    """
    # 1. Get current page number from request args, default to 1
    page = request.args.get("page", 1, type=int)

    # 2. Determine items per page from application config
    # Default to 5 if config not set
    per_page = current_app.config.get(per_page_config_key, 30)

    # 3. Perform pagination
    pagination = db.paginate(
        base_query,
        page=page,
        per_page=per_page,
        error_out=False,
    )

    # Helper function to generate URLs, ensuring extra args (like 'date') are included
    def generate_url(page_num):
        if page_num:
            # Combine 'page' arg with any extra args (**extra_args)
            return url_for(endpoint_name, page=page_num, **extra_args)
        return None

    # 4. Generate URLs
    next_url = generate_url(pagination.next_num)
    prev_url = generate_url(pagination.prev_num)

    return pagination, next_url, prev_url


def get_stock_purchase_history_query(date_filter=True, date_arg_key='date'):
    """
    Builds the base SQLAlchemy query for 'Historique des Achats Stock',
    optionally filtering by date from the request arguments.
    Automatically scopes results to the current user's vendeur via Stock join.

    Args:
        date_filter (bool): If True, applies the date filter based on request.args.
        date_arg_key (str): The key used in request.args for the date parameter.

    Returns:
        SQLAlchemy Query object: The base query, ordered by creation date (desc).
    """

    # Join Stock to allow filtering by vendeur_id (StockPurchase has no direct vendeur_id)
    query = (
        StockPurchase.query
        .join(Stock, StockPurchase.stock_item_id == Stock.id)
        .order_by(StockPurchase.created_at.desc())
    )

    # Apply vendeur filter — platform admin sees all
    vendeur_id = get_current_vendeur_id()
    if vendeur_id is not None:
        query = query.filter(Stock.vendeur_id == vendeur_id)

    # Apply date filter if requested
    if date_filter:
        ctx = get_date_context(arg_key=date_arg_key)

        # Apply the date range filtering using UTC timestamps
        query = query.filter(
            StockPurchase.created_at >= ctx['start_utc'],
            StockPurchase.created_at <= ctx['end_utc']
        )
        # Return the context needed by the endpoint for the frontend filter
        return query, ctx

    # If no date filter, just return the base query and an empty context
    return query, {}


def get_sales_history_query(date_filter=True, date_arg_key='date'):
    """
    Builds the base SQLAlchemy query for 'Historique des Ventes',
    optionally filtering by date from the request arguments.

    Args:
        date_filter (bool): If True, applies the date filter based on request.args.
        date_arg_key (str): The key used in request.args for the date parameter.

    Returns:
        tuple: (SQLAlchemy Query object, dict of date context)
    """

    # Start with the base query for the Sale model, ordered by creation date (desc)
    base_query = Sale.query.order_by(Sale.created_at.desc())
    filtered_query = filter_by_vendeur(base_query, Sale)
    # sales = filtered_query.all()
    # query = Sale.query.order_by(Sale.created_at.desc())

    # Apply date filter if requested
    if date_filter:
        ctx = get_date_context(arg_key=date_arg_key)

        # Apply the date range filtering using UTC timestamps
        query = filtered_query.filter(
            Sale.created_at >= ctx['start_utc'],
            Sale.created_at <= ctx['end_utc']
        )
        # Return the context needed by the endpoint for the frontend filter
        return query, ctx

    # If no date filter, just return the base query and an empty context
    return filtered_query, {}


def get_daily_report_data(
    app,
    target_date: date,
    start_of_utc_range: datetime,
    end_of_utc_range: datetime,
    vendeur_id: int = None,
):
    """
    Calculates comprehensive report data for a single target date based on live transactions.
    It includes the critical fix for the 'Initial Stock' calculation when no prior report exists.
    vendeur_id must be provided to scope all queries to a single business.
    """

    # Use the passed UTC ranges directly as they are correctly calculated by the caller (rapports)
    filter_start_dt = start_of_utc_range
    filter_end_dt = end_of_utc_range

    # 1. Setup Environment (Needed for determining is_live_report later in the loop)
    # The caller (rapports) already handles timezone conversion for TODAY.
    # We re-fetch TODAY's date to verify if target_date is TODAY for the 'Initial Stock' fix.
    (_, today_local_date_util, _, _) = get_local_timezone_datetime_info()

    is_live_report = (target_date == today_local_date_util)
    networks = list(NetworkType.__members__.values())
    report_results = {}
    total_sales_value_all = Decimal("0.00")

    # 2. Pre-fetch Live Data (Current State and Pricing) — scoped to this vendeur
    stock_query = Stock.query
    if vendeur_id is not None:
        stock_query = stock_query.filter_by(vendeur_id=vendeur_id)
    live_stock_items = stock_query.all()
    live_stock_map = {s.network: s for s in live_stock_items}

    # 3. Calculate Today's Movements (Purchases and Sales)

    # A. Purchases — filter through Stock.vendeur_id join
    purchases_query = (
        db.session.query(
            StockPurchase.network,
            func.sum(StockPurchase.amount_purchased).label("total")
        )
        .join(Stock, StockPurchase.stock_item_id == Stock.id)
        .filter(StockPurchase.created_at >= filter_start_dt, StockPurchase.created_at < filter_end_dt)
    )
    if vendeur_id is not None:
        purchases_query = purchases_query.filter(
            Stock.vendeur_id == vendeur_id)
    daily_purchases = purchases_query.group_by(StockPurchase.network).all()
    purchases_map = {p.network: Decimal(
        str(p.total or 0)) for p in daily_purchases}

    # B. Sales (Quantity & Value) — filter by Sale.vendeur_id
    sales_query = (
        db.session.query(
            SaleItem.network,
            func.sum(SaleItem.quantity).label("qty"),
            func.sum(SaleItem.subtotal).label("val")
        )
        .join(Sale)
        .filter(Sale.created_at >= filter_start_dt, Sale.created_at < filter_end_dt)
    )
    if vendeur_id is not None:
        sales_query = sales_query.filter(Sale.vendeur_id == vendeur_id)
    daily_sales = sales_query.group_by(SaleItem.network).all()
    sales_qty_map = {s.network: Decimal(str(s.qty or 0)) for s in daily_sales}
    sales_val_map = {s.network: Decimal(str(s.val or 0)) for s in daily_sales}

    # 4. Determine Previous Final Stock (Initial Stock Basis) — scoped to this vendeur
    previous_day = target_date - timedelta(days=1)
    prev_reports_query = DailyStockReport.query.filter_by(
        report_date=previous_day)
    if vendeur_id is not None:
        prev_reports_query = prev_reports_query.filter_by(
            vendeur_id=vendeur_id)
    previous_day_reports = prev_reports_query.all()
    previous_stock_map = {
        r.network: r.final_stock_balance for r in previous_day_reports}

    # 5. Calculate Debts (Cumulative up to end of period) — scoped to this vendeur
    # We query total outstanding debt at the Sale level (not per-network) to avoid
    # double-counting sales that span multiple networks.
    debt_query = (
        db.session.query(func.sum(Sale.debt_amount))
        .filter(
            Sale.debt_amount > 0,
            Sale.created_at <= filter_end_dt,
        )
    )
    if vendeur_id is not None:
        debt_query = debt_query.filter(Sale.vendeur_id == vendeur_id)
    total_debts_overall = debt_query.scalar() or Decimal("0.00")

    # Per-network debt map is kept as empty for display compatibility
    # (debt is shown as total, not broken down per network)
    network_debts_map = {network: Decimal("0.00") for network in networks}

    # 6. Build Final Report Data
    for network in networks:
        qty_purchased = purchases_map.get(network, Decimal("0.00"))
        qty_sold = sales_qty_map.get(network, Decimal("0.00"))
        val_sold = sales_val_map.get(network, Decimal("0.00"))

        live_item = live_stock_map.get(network)
        current_balance = live_item.balance if live_item else Decimal("0.00")
        selling_price = (
            live_item.selling_price_per_unit if live_item and live_item.selling_price_per_unit is not None
            else Decimal("1.00")
        )

        # --- STEP 6a: DETERMINE INITIAL STOCK (CRITICAL FIX) ---
        initial_stock = previous_stock_map.get(network)

        if initial_stock is None:
            # If no historical record exists for the day before...
            if is_live_report:
                # REVERSE CALCULATION for TODAY's report: Initial = Current + Sold - Purchased
                initial_stock = current_balance + qty_sold - qty_purchased

                app.logger.debug(
                    f"[{network.name}] LIVE FIX: Initial Stock reverse calculated to {initial_stock} "
                    f"from Current: {current_balance}, Sold: {qty_sold}, Purchased: {qty_purchased}."
                )
            else:
                # If it's a historical date AND no record exists, assume the start was 0.
                initial_stock = Decimal("0.00")

        # If initial_stock was found in history, ensure it's Decimal
        elif not isinstance(initial_stock, Decimal):
            initial_stock = Decimal(str(initial_stock))

        # --- STEP 6b: CALCULATE FINAL STOCK ---
        final_stock = initial_stock + qty_purchased - qty_sold

        # --- STEP 6c: OTHER METRICS ---
        virtual_value = final_stock * selling_price
        debt_amount = network_debts_map.get(network, Decimal("0.00"))

        # Store results
        report_results[network.name] = {
            "network": network,
            "initial_stock": initial_stock,
            "purchased_stock": qty_purchased,
            "sold_stock_quantity": qty_sold,
            "sold_stock_value": val_sold,
            "final_stock": final_stock,
            "virtual_value": virtual_value,
            "debt_amount": debt_amount,
        }

        total_sales_value_all += val_sold

    return (
        report_results,
        total_sales_value_all,
        total_debts_overall,
    )


def update_daily_reports(app, report_date_to_update=None, vendeur_id=None):
    """
    Calculates and updates DailyStockReport and DailyOverallReport for a given date.
    """
    with app.app_context():
        if report_date_to_update is None:
            report_date_to_update = date.today() - timedelta(days=1)

        app.logger.info(
            f"Generating/Updating daily reports for {report_date_to_update}, vendeur_id={vendeur_id}"
        )

        try:
            # 1. Calculate the necessary UTC date range
            start_utc, end_utc = get_utc_range_for_date(report_date_to_update)

            # 2. Get report data - PASS vendeur_id for filtering
            report_data, total_sales_from_transactions, total_debts_overall = (
                get_daily_report_data(
                    app,
                    report_date_to_update,
                    start_utc,
                    end_utc,
                    vendeur_id=vendeur_id  # ← ADD THIS if your function supports it
                )
            )

            total_initial_stock_day_overall = Decimal("0.00")
            total_purchased_stock_day_overall = Decimal("0.00")
            total_sold_stock_day_overall = Decimal("0.00")
            total_final_stock_day_overall = Decimal("0.00")
            total_virtual_value_day_overall = Decimal("0.00")

            for network_name, data in report_data.items():
                network = data["network"]

                # ✅ FIX: Include vendeur_id in query
                daily_report = DailyStockReport.query.filter_by(
                    network=network,
                    report_date=report_date_to_update,
                    vendeur_id=vendeur_id  # ← ADD THIS
                ).first()

                if not daily_report:
                    # ✅ FIX: Include vendeur_id when creating
                    daily_report = DailyStockReport(
                        network=network,
                        report_date=report_date_to_update,
                        vendeur_id=vendeur_id  # ← ADD THIS
                    )
                    db.session.add(daily_report)
                    app.logger.debug(
                        f"Creating new DailyStockReport for {network.name} on {report_date_to_update}"
                    )
                else:
                    app.logger.debug(
                        f"Updating DailyStockReport for {network.name} on {report_date_to_update}"
                    )

                daily_report.initial_stock_balance = data["initial_stock"]
                daily_report.purchased_stock_amount = data["purchased_stock"]
                daily_report.sold_stock_amount = data["sold_stock_quantity"]
                daily_report.final_stock_balance = data["final_stock"]
                daily_report.virtual_value = data["virtual_value"]
                daily_report.debt_amount = data["debt_amount"]

                total_initial_stock_day_overall += data["initial_stock"]
                total_purchased_stock_day_overall += data["purchased_stock"]
                total_sold_stock_day_overall += data["sold_stock_quantity"]
                total_final_stock_day_overall += data["final_stock"]
                total_virtual_value_day_overall += data["virtual_value"]

            # --- Update/Create DailyOverallReport ---
            overall_report = DailyOverallReport.query.filter_by(
                report_date=report_date_to_update,
                vendeur_id=vendeur_id,
            ).first()

            if not overall_report:
                overall_report = DailyOverallReport(
                    report_date=report_date_to_update,
                    vendeur_id=vendeur_id
                )
                db.session.add(overall_report)
                app.logger.debug(
                    f"Creating new DailyOverallReport for {report_date_to_update}"
                )
            else:
                app.logger.debug(
                    f"Updating DailyOverallReport for {report_date_to_update}"
                )

            overall_report.total_initial_stock = total_initial_stock_day_overall
            overall_report.total_purchased_stock = total_purchased_stock_day_overall
            overall_report.total_sold_stock = total_sold_stock_day_overall
            overall_report.total_final_stock = total_final_stock_day_overall
            overall_report.total_virtual_value = total_virtual_value_day_overall
            overall_report.total_debts = total_debts_overall
            overall_report.total_capital_circulant = total_virtual_value_day_overall
            overall_report.total_sales_from_transactions = total_sales_from_transactions

            db.session.commit()
            app.logger.info(
                f"Daily reports for {report_date_to_update} updated successfully."
            )

            # --- Sales Verification ---
            calculated_total_sold_stock = Decimal("0.00")
            for network_name, data in report_data.items():
                calculated_total_sold_stock += (
                    data["initial_stock"]
                    + data["purchased_stock"]
                    - data["final_stock"]
                )

            if calculated_total_sold_stock != total_sold_stock_day_overall:
                app.logger.warning(
                    f"Sales verification discrepancy for {report_date_to_update}: "
                    f"Calculated ({calculated_total_sold_stock:,.2f}) vs "
                    f"Actual ({total_sold_stock_day_overall:,.2f})"
                )
            else:
                app.logger.info(
                    f"Sales verification passed for {report_date_to_update}."
                )

        except Exception as e:
            app.logger.error(
                f"Error updating daily reports for {report_date_to_update}: {e}",
                exc_info=True,
            )
            db.session.rollback()
            raise


def load_seed_data():
    """Loads all seed data from the external JSON file."""
    try:
        # We need to access the app logger, so we check for current_app
        logger = current_app.logger if current_app else print

        with open(SEED_DATA_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Seed data file not found at {SEED_DATA_PATH}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {SEED_DATA_PATH}: {e}")
        return None


def seed_initial_stock_balances(app, seed_report_date: date, vendeur_id: int):
    """
    Seeds initial DailyStockReport entries and updates the live Stock table
    for a specific vendeur using data loaded from the external JSON config file.

    Args:
        app: Flask application instance
        seed_report_date: The date to use as the baseline report date
        vendeur_id: The vendeur whose stock to seed (required — no global seeding)
    """
    if vendeur_id is None:
        raise ValueError(
            "vendeur_id is required for seed_initial_stock_balances")

    # 1. Load Data
    full_seed_data = load_seed_data()
    if not full_seed_data:
        return

    # Extract the required sections from the JSON
    json_balances = full_seed_data.get("stock_balances", {})
    json_prices = full_seed_data.get("stock_prices", {})

    # Map JSON string keys to Python Enum keys for use in SQLAlchemy
    mapped_initial_balances = {
        NetworkType[network_name.upper()]: Decimal(str(balance))
        for network_name, balance in json_balances.items()
    }

    buying_price = Decimal(
        str(json_prices.get("buying_price_per_unit", "0.95")))
    selling_price = Decimal(
        str(json_prices.get("selling_price_per_unit", "1.00")))

    with app.app_context():
        app.logger.info(
            f"Seeding initial data for vendeur_id={vendeur_id} "
            f"on {seed_report_date} using JSON data."
        )

        try:
            with db.session.no_autoflush:
                # --- Phase 1: Update the live Stock table for this vendeur ---
                for network, balance_decimal in mapped_initial_balances.items():
                    stock_item = Stock.query.filter_by(
                        vendeur_id=vendeur_id, network=network
                    ).first()

                    if stock_item:
                        stock_item.balance = balance_decimal
                        stock_item.buying_price_per_unit = buying_price
                        stock_item.selling_price_per_unit = selling_price
                        app.logger.debug(
                            f"Updated Stock {network.name} for vendeur {vendeur_id}: "
                            f"balance={balance_decimal}"
                        )
                    else:
                        new_stock_item = Stock(
                            vendeur_id=vendeur_id,
                            network=network,
                            balance=balance_decimal,
                            buying_price_per_unit=buying_price,
                            selling_price_per_unit=selling_price,
                        )
                        db.session.add(new_stock_item)
                        app.logger.debug(
                            f"Created Stock {network.name} for vendeur {vendeur_id}: "
                            f"balance={balance_decimal}"
                        )

                # --- Phase 2: Create/Update DailyStockReport for the seed date ---
                for network, initial_balance_decimal in mapped_initial_balances.items():
                    # Virtual value uses SELLING price (consistent with live report calculation)
                    virtual_value = initial_balance_decimal * selling_price

                    report = DailyStockReport.query.filter_by(
                        report_date=seed_report_date,
                        network=network,
                        vendeur_id=vendeur_id,
                    ).first()

                    if report:
                        app.logger.debug(
                            f"Updating seed DailyStockReport {network.name} "
                            f"vendeur={vendeur_id} date={seed_report_date}"
                        )
                    else:
                        report = DailyStockReport(
                            report_date=seed_report_date,
                            network=network,
                            vendeur_id=vendeur_id,
                        )
                        db.session.add(report)
                        app.logger.debug(
                            f"Creating seed DailyStockReport {network.name} "
                            f"vendeur={vendeur_id} date={seed_report_date}"
                        )

                    report.initial_stock_balance = initial_balance_decimal
                    report.purchased_stock_amount = Decimal("0.00")
                    report.sold_stock_amount = Decimal("0.00")
                    report.final_stock_balance = initial_balance_decimal
                    report.virtual_value = virtual_value
                    report.debt_amount = Decimal("0.00")

                # --- Phase 3: Create/Update DailyOverallReport for the seed date ---
                # Re-fetch only THIS vendeur's reports for the seed date
                all_seeded_reports = DailyStockReport.query.filter_by(
                    report_date=seed_report_date,
                    vendeur_id=vendeur_id,
                ).all()

                total_initial = sum(
                    Decimal(str(r.initial_stock_balance)) for r in all_seeded_reports
                )
                total_final = sum(
                    Decimal(str(r.final_stock_balance)) for r in all_seeded_reports
                )
                total_virtual = sum(
                    Decimal(str(r.virtual_value)) for r in all_seeded_reports
                )

                overall_report = DailyOverallReport.query.filter_by(
                    report_date=seed_report_date,
                    vendeur_id=vendeur_id,
                ).first()

                if not overall_report:
                    overall_report = DailyOverallReport(
                        report_date=seed_report_date,
                        vendeur_id=vendeur_id,
                    )
                    db.session.add(overall_report)

                overall_report.total_initial_stock = total_initial
                overall_report.total_purchased_stock = Decimal("0.00")
                overall_report.total_sold_stock = Decimal("0.00")
                overall_report.total_final_stock = total_final
                overall_report.total_virtual_value = total_virtual
                overall_report.total_debts = Decimal("0.00")

            db.session.commit()
            app.logger.info(
                f"Seed complete for vendeur_id={vendeur_id} on {seed_report_date}."
            )

        except Exception as e:
            app.logger.error(
                f"Error seeding data for vendeur_id={vendeur_id}: {e}", exc_info=True
            )
            db.session.rollback()
            raise

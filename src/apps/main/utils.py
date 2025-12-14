import json
import os
from pathlib import Path
from decimal import Decimal
from apps import db
from flask import current_app, request, url_for
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
    Initializes default stock entries for each network type if they don't exist.
    """
    with app.app_context():
        # Only initialize if no stock items exist at all,
        # otherwise, seed_initial_stock_balances handles specific initial values.
        if not Stock.query.first():
            for network_type in NetworkType:
                if not Stock.query.filter_by(network=network_type).first():
                    initial_stock_item = Stock(
                        network=network_type,
                        balance=0,
                        buying_price_per_unit=Decimal("26.79"),
                        selling_price_per_unit=Decimal(
                            "27.00"
                        ),  # Ensure a selling price is set
                    )
                    db.session.add(initial_stock_item)
                    current_app.logger.info(
                        f"Initialized Stock for {network_type.value}"
                    )
            db.session.commit()
            current_app.logger.info("Stock initialization complete.")
        else:
            current_app.logger.info(
                "Stock items already exist, skipping default initialization."
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
    start_local = datetime.combine(target_date, time.min) # 00:00:00
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
    per_page = current_app.config.get(per_page_config_key, 5) # Default to 5 if config not set

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


def get_daily_report_data(
    app,
    target_date: date,
    start_of_utc_range: datetime,
    end_of_utc_range: datetime,
):
    """
    Calculates comprehensive report data for a single target date based on live transactions.
    It includes the critical fix for the 'Initial Stock' calculation when no prior report exists.
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

    # 2. Pre-fetch Live Data (Current State and Pricing)
    live_stock_items = Stock.query.all()
    live_stock_map = {s.network: s for s in live_stock_items}

    # 3. Calculate Today's Movements (Purchases and Sales)
    
    # A. Purchases
    daily_purchases = (
        db.session.query(
            StockPurchase.network,
            func.sum(StockPurchase.amount_purchased).label("total")
        )
        .filter(StockPurchase.created_at >= filter_start_dt, StockPurchase.created_at < filter_end_dt)
        .group_by(StockPurchase.network)
        .all()
    )
    purchases_map = {p.network: Decimal(str(p.total or 0)) for p in daily_purchases}

    # B. Sales (Quantity & Value)
    daily_sales = (
        db.session.query(
            SaleItem.network,
            func.sum(SaleItem.quantity).label("qty"),
            func.sum(SaleItem.subtotal).label("val")
        )
        .join(Sale)
        .filter(Sale.created_at >= filter_start_dt, Sale.created_at < filter_end_dt)
        .group_by(SaleItem.network)
        .all()
    )
    sales_qty_map = {s.network: Decimal(str(s.qty or 0)) for s in daily_sales}
    sales_val_map = {s.network: Decimal(str(s.val or 0)) for s in daily_sales}

    # 4. Determine Previous Final Stock (Initial Stock Basis)
    previous_day = target_date - timedelta(days=1)
    previous_day_reports = DailyStockReport.query.filter_by(report_date=previous_day).all()
    previous_stock_map = {r.network: r.final_stock_balance for r in previous_day_reports}

    # 5. Calculate Debts (Cumulative up to end of period)
    network_debts_map = {}
    for network in networks:
        debt_query = (
            db.session.query(func.sum(Sale.debt_amount))
            .join(SaleItem)
            .filter(
                SaleItem.network == network,
                Sale.debt_amount > 0,
                Sale.created_at <= filter_end_dt,
            )
        )
        network_debts_map[network] = debt_query.scalar() or Decimal("0.00")

    total_debts_overall = sum(network_debts_map.values(), Decimal("0.00"))

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


# Change this and user a button to register daily reports
def update_daily_reports(app, report_date_to_update=None):
    """
    Calculates and updates DailyStockReport and DailyOverallReport for a given date.
    This should be run daily, ideally after all transactions for the day are recorded.
    This function will be called by APScheduler or CLI.
    """
    with app.app_context():
        if report_date_to_update is None:
            # When called by scheduler or without specific date, default to yesterday
            # so that it processes a full day's data from the previous day.
            # If you want it to always calculate for "today", set this to date.today()
            # but then ensure your scheduler runs after all transactions for "today" are complete.
            report_date_to_update = date.today() - timedelta(days=1)

        app.logger.info(
            f"Generating/Updating daily reports for {report_date_to_update}"
        )

        try:
            # Use the new generalized function to get all calculated data
            report_data, total_sales_from_transactions, total_debts_overall = (
                get_daily_report_data(app, report_date_to_update)
            )

            total_initial_stock_day_overall = Decimal("0.00")
            total_purchased_stock_day_overall = Decimal("0.00")
            total_sold_stock_day_overall = Decimal("0.00")
            total_final_stock_day_overall = Decimal("0.00")
            total_virtual_value_day_overall = Decimal("0.00")

            for network_name, data in report_data.items():
                network = data["network"]

                daily_report = DailyStockReport.query.filter_by(
                    network=network, report_date=report_date_to_update
                ).first()

                if not daily_report:
                    daily_report = DailyStockReport(
                        network=network, report_date=report_date_to_update
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

            # --- Update/Create DailyOverallReport for the target_date ---
            overall_report = DailyOverallReport.query.filter_by(
                report_date=report_date_to_update
            ).first()

            if not overall_report:
                overall_report = DailyOverallReport(report_date=report_date_to_update)
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

            # --- Perform Sales Verification ---
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
                    f"Calculated Sold Stock ({calculated_total_sold_stock:,.2f}) "
                    f"does NOT match Actual Sold Stock from Transactions ({total_sold_stock_day_overall:,.2f}). "
                    "Possible forgotten sale registration."
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


def seed_initial_stock_balances(app, seed_report_date: date):
    """
    Seeds initial DailyStockReport entries and updates the live Stock table
    using data loaded from the external JSON configuration file.
    """

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

    buying_price_str = str(
        Decimal(str(json_prices.get("buying_price_per_unit", "0.95")))
    )
    selling_price_str = str(
        Decimal(str(json_prices.get("selling_price_per_unit", "1.00")))
    )

    with app.app_context():
        app.logger.info(
            f"Seeding initial DailyStockReport for {seed_report_date} and Stock table using JSON data."
        )

        try:
            with db.session.no_autoflush:
                # --- Phase 1: Ensure the live Stock table has corresponding initial balances ---
                for network, balance_decimal in mapped_initial_balances.items():
                    stock_item = Stock.query.filter_by(network=network).first()

                    # Values are already Decimal in Python, convert to string ONLY for DB assignment
                    balance_str = str(balance_decimal)

                    if stock_item:
                        stock_item.balance = balance_str
                        app.logger.debug(
                            f"Updated live Stock balance for {network.name} to {balance_str} (from JSON)."
                        )
                    else:
                        new_stock_item = Stock(
                            network=network,
                            balance=balance_str,
                            buying_price_per_unit=buying_price_str,
                            selling_price_per_unit=selling_price_str,
                        )
                        db.session.add(new_stock_item)
                        app.logger.debug(
                            f"Created live Stock item for {network.name} with balance {balance_str} (from JSON)."
                        )

                # --- Phase 2 & 3 (DailyStockReport and DailyOverallReport creation) ---
                # NOTE: The rest of the logic remains unchanged, as it now correctly loops
                # through the properly mapped `mapped_initial_balances` dictionary (which is aliased here).

                # Use mapped_initial_balances for the rest of the seeding logic
                initial_balances_for_seed = mapped_initial_balances

                # ... (Rest of the original Phase 2 & 3 logic is correct and omitted here for brevity) ...

                # --- Phase 2: Create/Update the DailyStockReport for the seed_report_date ---
                for (
                    network,
                    initial_balance_decimal,
                ) in mapped_initial_balances.items():  # Use the mapped dictionary
                    # ... (Existing Report Logic)
                    # NOTE: Ensure you complete the rest of the original function logic here.

                    report = DailyStockReport.query.filter_by(
                        report_date=seed_report_date, network=network
                    ).first()

                    current_stock_item_for_price = Stock.query.filter_by(
                        network=network
                    ).first()

                    # Ensure price conversion is safe (from string in DB back to Decimal)
                    buying_price_for_virtual_decimal = Decimal("0.00")
                    if (
                        current_stock_item_for_price
                        and current_stock_item_for_price.buying_price_per_unit
                        is not None
                    ):
                        try:
                            buying_price_for_virtual_decimal = Decimal(
                                str(current_stock_item_for_price.buying_price_per_unit)
                            )
                        except Exception:
                            buying_price_for_virtual_decimal = Decimal("0.00")

                    virtual_value_calculated_decimal = (
                        initial_balance_decimal * buying_price_for_virtual_decimal
                    )

                    # Convert all relevant Decimal values to string before assigning/adding
                    initial_stock_str = str(initial_balance_decimal)
                    purchased_stock_str = str(Decimal("0.00"))
                    sold_stock_str = str(Decimal("0.00"))
                    final_stock_str = str(initial_balance_decimal)
                    virtual_value_str = str(virtual_value_calculated_decimal)
                    debt_amount_str = str(Decimal("0.00"))

                    if report:
                        app.logger.debug(
                            f"Updating seed report for {network.name} on {seed_report_date}."
                        )
                        report.initial_stock_balance = initial_stock_str
                        report.final_stock_balance = final_stock_str
                        report.purchased_stock_amount = purchased_stock_str
                        report.sold_stock_amount = sold_stock_str
                        report.virtual_value = virtual_value_str
                        report.debt_amount = debt_amount_str
                    else:
                        app.logger.debug(
                            f"Creating seed report for {network.name} on {seed_report_date}."
                        )
                        new_report = DailyStockReport(
                            report_date=seed_report_date,
                            network=network,
                            initial_stock_balance=initial_stock_str,
                            purchased_stock_amount=purchased_stock_str,
                            sold_stock_amount=sold_stock_str,
                            final_stock_balance=final_stock_str,
                            virtual_value=virtual_value_str,
                            debt_amount=debt_amount_str,
                        )
                        db.session.add(new_report)

                # --- Phase 3: Manual creation/update for DailyOverallReport for the seed date ---
                all_seeded_daily_reports = DailyStockReport.query.filter_by(
                    report_date=seed_report_date
                ).all()

                # Recalculate sums using Decimal conversion from DB value
                total_initial = sum(
                    Decimal(str(r.initial_stock_balance))
                    for r in all_seeded_daily_reports
                )
                total_final = sum(
                    Decimal(str(r.final_stock_balance))
                    for r in all_seeded_daily_reports
                )
                total_virtual = sum(
                    Decimal(str(r.virtual_value)) for r in all_seeded_daily_reports
                )
                total_debts_overall = Decimal(
                    "0.00"
                )  # Hardcoded to 0.00 for initial seed

                overall_seed_report = DailyOverallReport.query.filter_by(
                    report_date=seed_report_date
                ).first()

                # Convert all relevant Decimal values to string before assigning/adding
                total_initial_str = str(total_initial)
                total_purchased_str = str(Decimal("0.00"))
                total_sold_str = str(Decimal("0.00"))
                total_final_str = str(total_final)
                total_virtual_str = str(total_virtual)
                total_debts_overall_str = str(total_debts_overall)
                total_capital_circulant_str = str(total_virtual)
                total_sales_from_transactions_str = str(Decimal("0.00"))

                if overall_seed_report:
                    overall_seed_report.total_initial_stock = total_initial_str
                    overall_seed_report.total_final_stock = total_final_str
                    overall_seed_report.total_virtual_value = total_virtual_str
                    overall_seed_report.total_purchased_stock = total_purchased_str
                    overall_seed_report.total_sold_stock = total_sold_str
                    overall_seed_report.total_debts = total_debts_overall_str
                    overall_seed_report.total_capital_circulant = (
                        total_capital_circulant_str
                    )
                    overall_seed_report.total_sales_from_transactions = (
                        total_sales_from_transactions_str
                    )
                else:
                    overall_seed_report = DailyOverallReport(
                        report_date=seed_report_date,
                        total_initial_stock=total_initial_str,
                        total_purchased_stock=total_purchased_str,
                        total_sold_stock=total_sold_str,
                        total_final_stock=total_final_str,
                        total_virtual_value=total_virtual_str,
                        total_debts=total_debts_overall_str,
                    )
                    db.session.add(overall_seed_report)

            db.session.commit()
            app.logger.info(
                f"Initial stock report and live stock for {seed_report_date} seeded successfully."
            )

        except Exception as e:
            app.logger.error(f"Error seeding initial report data: {e}", exc_info=True)
            db.session.rollback()
            raise  # Re-raise the exception to fail the setup command



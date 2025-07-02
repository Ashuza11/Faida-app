from apps import db
from flask import current_app
from apps.authentication.models import (
    DailyStockReport,
    NetworkType,
    Stock,
    StockPurchase,
    Sale,
    SaleItem,
    DailyOverallReport,
)
from decimal import Decimal, ROUND_UP, getcontext
from datetime import date, datetime, timedelta, time, timezone
import pytz
from sqlalchemy import func

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
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            current_app.logger.warning(
                f"Invalid date format received: {date_str}. Using default."
            )
            return default_date
    return default_date


def get_daily_report_data(
    app,
    target_date: date,
    start_of_utc_range: datetime = None,  # Keep these for explicit overrides if needed, but the primary use for 'today' will be the new utility
    end_of_utc_range: datetime = None,
):
    """
    Calculates comprehensive report data for a *single specific date* (target_date).
    This function gathers data from live transactions and previous day's reports
    to present the 'initial', 'purchased', 'sold', 'final', 'virtual', and 'debt'
    figures for each network for the target_date.

    This data can be used for both real-time display (if target_date is today)
    and for generating/updating historical daily reports.

    Args:
        app: Flask app instance.
        target_date (date): The calendar date (local) for which the report is being generated.
        start_of_utc_range (datetime, optional): Explicit UTC datetime for the start of the filter period.
                                                Used for live reports to align with local day.
        end_of_utc_range (datetime, optional): Explicit UTC datetime for the end of the filter period.
                                              Used for live reports to align with local day.
    """
    with app.app_context():
        app.logger.info(f"Calculating report data for target date: {target_date}")

        (
            _,
            today_local_date_util,
            start_of_local_day_utc_util,
            end_of_local_day_utc_util,
        ) = get_local_timezone_datetime_info()

        # Determine the datetime range for filtering.
        if target_date == today_local_date_util:
            # If target_date is today, use the live local-day-aligned UTC range from the utility
            filter_start_dt = start_of_local_day_utc_util
            filter_end_dt = end_of_local_day_utc_util
            app.logger.info(
                f"For target_date (today), using live UTC filter range: {filter_start_dt} to {filter_end_dt}"
            )
        elif start_of_utc_range and end_of_utc_range:
            # Fallback for explicit overrides, although the above 'today' check is usually sufficient
            filter_start_dt = start_of_utc_range
            filter_end_dt = end_of_utc_range
            app.logger.info(
                f"Using explicit UTC filter range: {filter_start_dt} to {filter_end_dt}"
            )
        else:
            # For historical reports (target_date is not today), filter based on the target_date's UTC day
            # This logic assumes historical data timestamps are stored in UTC and correspond directly to a UTC day.
            # If your historical `report_date` in DailyOverallReport/DailyStockReport refers to a LOCAL date,
            # but transactions (`created_at`) are UTC, then this needs to properly convert `target_date` (local)
            # into its corresponding UTC range.
            # The current way (`datetime.combine(target_date, time.min, tzinfo=timezone.utc)`) assumes target_date
            # *is* the UTC date, which might not be what you want for historical data that was *generated* for a local day.
            # Let's adjust this to be robust:
            filter_start_dt = APP_TIMEZONE.localize(
                datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)
            ).astimezone(pytz.utc)
            filter_end_dt = APP_TIMEZONE.localize(
                datetime(
                    target_date.year,
                    target_date.month,
                    target_date.day,
                    23,
                    59,
                    59,
                    999999,
                )
            ).astimezone(pytz.utc)
            app.logger.info(
                f"Calculating UTC filter range for historical target_date {target_date}: {filter_start_dt} to {filter_end_dt}"
            )

        networks = list(NetworkType.__members__.values())
        report_results = {}
        total_sales_from_transactions_all_networks = Decimal("0.00")
        total_debts_overall = Decimal("0.00")  # Initialize here

        # Get previous day's final stock balances to use as current day's initial stock
        previous_day = target_date - timedelta(days=1)
        previous_day_reports = DailyStockReport.query.filter_by(
            report_date=previous_day
        ).all()
        previous_final_stocks_map = {
            r.network: r.final_stock_balance for r in previous_day_reports
        }

        # Fetch live stock items to get current buying/selling prices
        live_stock_items = Stock.query.all()
        live_stock_map = {s.network: s for s in live_stock_items}

        # Calculate daily purchases for the target_date
        daily_purchases_query = (
            db.session.query(
                StockPurchase.network,
                func.sum(StockPurchase.amount_purchased).label(
                    "total_purchased_amount"
                ),
            )
            .filter(
                StockPurchase.created_at >= filter_start_dt,
                StockPurchase.created_at < filter_end_dt,
            )
            .group_by(StockPurchase.network)
        )
        # Add a logger for the SQL query generated
        app.logger.debug(
            f"Daily purchases SQL: {daily_purchases_query.statement.compile(dialect=db.engine.dialect)}"
        )
        daily_purchases = daily_purchases_query.all()

        purchases_by_network = {
            p.network: Decimal(str(p.total_purchased_amount or 0))
            for p in daily_purchases
        }

        # Calculate daily sales (quantity sold) for the target_date
        daily_sales_quantity_query = (
            db.session.query(
                SaleItem.network,
                func.sum(SaleItem.quantity).label("total_sold_quantity"),
            )
            .join(Sale)
            .filter(
                Sale.created_at >= filter_start_dt,
                Sale.created_at < filter_end_dt,
            )
            .group_by(SaleItem.network)
        )
        # Add a logger for the SQL query generated
        app.logger.debug(
            f"Daily sales quantity SQL: {daily_sales_quantity_query.statement.compile(dialect=db.engine.dialect)}"
        )
        daily_sales_quantity = daily_sales_quantity_query.all()

        sold_quantities_by_network = {
            s.network: Decimal(str(s.total_sold_quantity or 0))
            for s in daily_sales_quantity
        }

        # Calculate daily sales (total monetary value) for the target_date
        daily_sales_value_query = (
            db.session.query(
                SaleItem.network,
                func.sum(SaleItem.subtotal).label("total_sold_value"),
            )
            .join(Sale)
            .filter(
                Sale.created_at >= filter_start_dt,
                Sale.created_at < filter_end_dt,
            )
            .group_by(SaleItem.network)
        )
        # Add a logger for the SQL query generated
        app.logger.debug(
            f"Daily sales value SQL: {daily_sales_value_query.statement.compile(dialect=db.engine.dialect)}"
        )
        daily_sales_value = daily_sales_value_query.all()

        sold_values_by_network = {
            s.network: Decimal(str(s.total_sold_value or 0)) for s in daily_sales_value
        }

        # Calculate network-specific debts as of target_date
        # For debts, you want all *outstanding* debts created up to the end of the filter period.
        # This is cumulative.
        network_debts = {}
        for network in networks:
            current_network_debts_query = (
                db.session.query(func.sum(Sale.debt_amount))
                .join(SaleItem)
                .filter(
                    SaleItem.network == network,
                    Sale.debt_amount > 0,
                    Sale.created_at
                    <= filter_end_dt,  # All outstanding debts up to end of period
                )
            )
            # Debug SQL for debts as well
            app.logger.debug(
                f"Debt query SQL for {network.name}: {current_network_debts_query.statement.compile(dialect=db.engine.dialect)}"
            )
            debt_sum = current_network_debts_query.scalar() or Decimal("0.00")
            network_debts[network] = debt_sum

        # Aggregate total debts across all networks for the grand total
        total_debts_overall = sum(network_debts.values(), Decimal("0.00"))

        for network in networks:
            initial_stock = previous_final_stocks_map.get(
                network, Decimal("0.00")
            )  # Default to 0

            # If no previous day's report, or if target_date is today,
            # fall back to the live stock balance for initial stock.
            # This ensures live data for today's report starts from current stock.
            # For historical reports, we should rely on the previous_final_stocks_map.
            if (
                target_date == today_local_date_util and not initial_stock
            ):  # Check if initial_stock is 0 or not found
                live_stock = live_stock_map.get(network)
                initial_stock = live_stock.balance if live_stock else Decimal("0.00")
                app.logger.debug(
                    f"For live report ({target_date}), no previous day report for {network.name}. "
                    f"Using live stock as initial: {initial_stock}"
                )

            purchased_stock = purchases_by_network.get(network, Decimal("0.00"))
            sold_stock_quantity = sold_quantities_by_network.get(
                network, Decimal("0.00")
            )
            sold_stock_value = sold_values_by_network.get(network, Decimal("0.00"))

            final_stock = initial_stock + purchased_stock - sold_stock_quantity

            selling_price_per_unit = Decimal("0.00")
            if live_stock_map.get(network):
                selling_price_per_unit = live_stock_map[
                    network
                ].selling_price_per_unit or Decimal("1.00")

            virtual_value = final_stock * selling_price_per_unit

            debt_amount = network_debts.get(network, Decimal("0.00"))

            report_results[network.name] = {
                "network": network,
                "initial_stock": initial_stock,
                "purchased_stock": purchased_stock,
                "sold_stock_quantity": sold_stock_quantity,
                "sold_stock_value": sold_stock_value,
                "final_stock": final_stock,
                "virtual_value": virtual_value,
                "debt_amount": debt_amount,
            }
            total_sales_from_transactions_all_networks += sold_stock_value

        return (
            report_results,
            total_sales_from_transactions_all_networks,
            total_debts_overall,
        )


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


def seed_initial_stock_balances(app, seed_report_date: date):
    """
    Seeds initial DailyStockReport entries for a specific historical date (e.g., Day 0)
    to provide a starting point for 'initial_stock_balance' for subsequent reports.
    Also ensures the live Stock table has corresponding initial balances.
    """
    initial_balances_for_seed = {
        NetworkType.AIRTEL: Decimal("11731.00"),
        NetworkType.ORANGE: Decimal("4694.00"),
        NetworkType.VODACOM: Decimal("8533.00"),
        NetworkType.AFRICEL: Decimal("4073.00"),
    }

    with app.app_context():
        app.logger.info(
            f"Seeding initial DailyStockReport for {seed_report_date} and Stock table."
        )

        try:
            with db.session.no_autoflush:
                # --- Phase 1: Ensure the live Stock table has corresponding initial balances ---
                for network, balance_decimal in initial_balances_for_seed.items():
                    stock_item = Stock.query.filter_by(network=network).first()

                    # Convert Decimal to string ONLY IF you have db.Numeric and not DecimalToString
                    # If you have DecimalToString, this conversion is done automatically.
                    # This is the "fix without changing model" part you asked for,
                    # but it's very manual and error-prone.
                    balance_str = str(balance_decimal)
                    buying_price_str = str(Decimal("0.95"))
                    selling_price_str = str(Decimal("1.00"))

                    if stock_item:
                        stock_item.balance = balance_str  # Assign the string here
                        app.logger.debug(
                            f"Updated live Stock balance for {network.name} to {balance_str} (as string)."
                        )
                    else:
                        new_stock_item = Stock(
                            network=network,
                            balance=balance_str,  # Assign the string here
                            buying_price_per_unit=buying_price_str,  # Assign the string here
                            selling_price_per_unit=selling_price_str,  # Assign the string here
                        )
                        db.session.add(new_stock_item)
                        app.logger.debug(
                            f"Created live Stock item for {network.name} with balance {balance_str} (as string)."
                        )

                # --- Phase 2: Create/Update the DailyStockReport for the seed_report_date ---
                for (
                    network,
                    initial_balance_decimal,
                ) in initial_balances_for_seed.items():
                    report = DailyStockReport.query.filter_by(
                        report_date=seed_report_date, network=network
                    ).first()

                    current_stock_item_for_price = Stock.query.filter_by(
                        network=network
                    ).first()
                    buying_price_for_virtual_decimal = Decimal("0.00")
                    if (
                        current_stock_item_for_price
                        and current_stock_item_for_price.buying_price_per_unit
                        is not None
                    ):
                        # Important: If current_stock_item_for_price.buying_price_per_unit
                        # is stored as string in DB, you need to convert it back to Decimal here
                        try:
                            buying_price_for_virtual_decimal = Decimal(
                                str(current_stock_item_for_price.buying_price_per_unit)
                            )
                        except Exception:
                            buying_price_for_virtual_decimal = Decimal(
                                "0.00"
                            )  # Handle conversion error

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

                # These sums will now work correctly assuming all_seeded_daily_reports
                # have their values as Decimal (because they were converted by DecimalToString
                # on retrieval if the model IS using it, or if you manually convert here).
                # If you are NOT using DecimalToString, and the DB stores strings,
                # you'd need to convert these to Decimal first for the sum.
                # Assuming they are Decimal now (either by DecimalToString or by explicit conversion above):
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
                total_debts_overall = Decimal("0.00")

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
            raise

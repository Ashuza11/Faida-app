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
from datetime import date, datetime, timedelta, time
from decimal import Decimal
from sqlalchemy import func
from sqlalchemy.sql import cast
from sqlalchemy.types import Date


def initialize_stock_items(app):
    """
    Initializes default stock entries for each network type if they don't exist.
    """
    with app.app_context():
        for network_type in NetworkType:
            if not Stock.query.filter_by(network=network_type).first():
                initial_stock_item = Stock(
                    network=network_type,
                    balance=0,
                    buying_price_per_unit=26.79,  # 26.79 >
                )
                db.session.add(initial_stock_item)
                app.logger.info(f"Initialized Stock for {network_type.value}")
        db.session.commit()
        app.logger.info("Stock initialization complete.")


# Set precision for Decimal operations
getcontext().prec = 10


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


def get_daily_report_data(app, target_date: date):
    """
    Calculates comprehensive report data for a *single specific date* (target_date).
    This function gathers data from live transactions and previous day's reports
    to present the 'initial', 'purchased', 'sold', 'final', 'virtual', and 'debt'
    figures for each network for the target_date.

    This data can be used for both real-time display (if target_date is today)
    and for generating/updating historical daily reports.
    """
    with app.app_context():
        app.logger.info(f"Calculating report data for target date: {target_date}")

        # Define the start and end of the target day for robust datetime filtering
        # Start of target_date (e.g., 2025-06-29 00:00:00)
        start_of_target_day = datetime.combine(target_date, time.min)
        # Start of the next day (e.g., 2025-06-30 00:00:00)
        end_of_target_day = datetime.combine(target_date + timedelta(days=1), time.min)

        app.logger.info(
            f"Filtering transactions between: {start_of_target_day} and {end_of_target_day}"
        )

        networks = list(NetworkType.__members__.values())
        report_results = {}
        total_sales_from_transactions_all_networks = Decimal("0.00")

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
        daily_purchases_query = (  # Renamed to avoid confusion with the list
            db.session.query(
                StockPurchase.network,
                func.sum(StockPurchase.amount_purchased).label(
                    "total_purchased_amount"
                ),
            )
            # CHANGE HERE: Use datetime range instead of cast(Date)
            .filter(
                StockPurchase.created_at >= start_of_target_day,
                StockPurchase.created_at < end_of_target_day,
            ).group_by(StockPurchase.network)
        )
        # Add a logger for the SQL query generated
        app.logger.debug(
            f"Daily purchases SQL: {daily_purchases_query.statement.compile(dialect=db.engine.dialect)}"
        )
        daily_purchases = daily_purchases_query.all()  # Fetch the results here

        purchases_by_network = {
            p.network: Decimal(str(p.total_purchased_amount or 0))
            for p in daily_purchases
        }

        # Calculate daily sales (quantity sold) for the target_date
        daily_sales_quantity_query = (  # Renamed to avoid confusion with the list
            db.session.query(
                SaleItem.network,
                func.sum(SaleItem.quantity).label("total_sold_quantity"),
            )
            .join(Sale)
            # CHANGE HERE: Use datetime range instead of cast(Date)
            .filter(
                Sale.created_at >= start_of_target_day,
                Sale.created_at < end_of_target_day,
            )
            .group_by(SaleItem.network)
        )
        # Add a logger for the SQL query generated
        app.logger.debug(
            f"Daily sales quantity SQL: {daily_sales_quantity_query.statement.compile(dialect=db.engine.dialect)}"
        )
        daily_sales_quantity = (
            daily_sales_quantity_query.all()
        )  # Fetch the results here

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
            # CHANGE HERE: Use datetime range instead of cast(Date)
            .filter(
                Sale.created_at >= start_of_target_day,
                Sale.created_at < end_of_target_day,
            )
            .group_by(SaleItem.network)
        )
        # Add a logger for the SQL query generated
        app.logger.debug(
            f"Daily sales value SQL: {daily_sales_value_query.statement.compile(dialect=db.engine.dialect)}"
        )
        daily_sales_value = daily_sales_value_query.all()  # Fetch the results here

        sold_values_by_network = {
            s.network: Decimal(str(s.total_sold_value or 0)) for s in daily_sales_value
        }

        # Calculate network-specific debts as of target_date
        network_debts = {}
        for network in networks:
            current_network_debts_query = (
                db.session.query(func.sum(Sale.debt_amount))
                .join(SaleItem)
                .filter(
                    SaleItem.network == network,
                    Sale.debt_amount > 0,
                    # For debts, you want all debts *up to and including* the target date
                    # So, still use a range, but allow it to be <= end of day
                    Sale.created_at
                    < end_of_target_day,  # Debts accrued up to end of this day
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
            initial_stock = previous_final_stocks_map.get(network, None)

            # If no previous day's report, or if target_date is today,
            # fall back to the live stock balance. This is crucial for real-time reports.
            if initial_stock is None:
                live_stock = live_stock_map.get(network)
                initial_stock = live_stock.balance if live_stock else Decimal("0.00")
                app.logger.debug(
                    f"No previous day report for {network.name} on {target_date}. "
                    f"Using live stock as initial: {initial_stock}"
                )

            purchased_stock = purchases_by_network.get(network, Decimal("0.00"))
            sold_stock_quantity = sold_quantities_by_network.get(
                network, Decimal("0.00")
            )
            sold_stock_value = sold_values_by_network.get(
                network, Decimal("0.00")
            )  # This is total sales value for validation

            final_stock = initial_stock + purchased_stock - sold_stock_quantity

            # Get selling price for virtual value calculation
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
            report_date_to_update = date.today()

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
                daily_report.sold_stock_amount = data[
                    "sold_stock_quantity"
                ]  # Store quantity sold
                daily_report.final_stock_balance = data["final_stock"]
                daily_report.virtual_value = data["virtual_value"]
                daily_report.debt_amount = data[
                    "debt_amount"
                ]  # Cumulative debt for the network up to this day

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
            overall_report.total_debts = (
                total_debts_overall  # Total cumulative debts across all networks
            )
            # Assuming total_capital_circulant is total_virtual_value as per your seed function
            overall_report.total_capital_circulant = total_virtual_value_day_overall
            # Store total sales from transactions for verification later if needed
            overall_report.total_sales_from_transactions = total_sales_from_transactions

            db.session.commit()
            app.logger.info(
                f"Daily reports for {report_date_to_update} updated successfully."
            )

        except Exception as e:
            app.logger.error(
                f"Error updating daily reports for {report_date_to_update}: {e}",
                exc_info=True,
            )
            db.session.rollback()
            raise  # Re-raise for error visibility


# Existing seed function (keep as is, or modify if you need specific seeding logic for tests)
def seed_initial_stock_balances(app):
    """
    Seeds initial DailyStockReport entries for a specific historical date (e.g., Day 0)
    to provide a starting point for 'initial_stock_balance' for subsequent reports.
    Also ensures the live Stock table has corresponding initial balances.
    """
    # Define the date for the "Day 0" report
    seed_report_date = date(2025, 6, 27)

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
                for network, balance in initial_balances_for_seed.items():
                    stock_item = Stock.query.filter_by(network=network).first()
                    if stock_item:
                        stock_item.balance = balance
                        app.logger.debug(
                            f"Updated live Stock balance for {network.name} to {balance}."
                        )
                    else:
                        new_stock_item = Stock(
                            network=network,
                            balance=balance,
                            buying_price_per_unit=Decimal("0.95"),
                            selling_price_per_unit=Decimal("1.00"),
                        )
                        db.session.add(new_stock_item)
                        app.logger.debug(
                            f"Created live Stock item for {network.name} with balance {balance}."
                        )

                # --- Phase 2: Create/Update the DailyStockReport for the seed_report_date ---
                for network, initial_balance in initial_balances_for_seed.items():
                    report = DailyStockReport.query.filter_by(
                        report_date=seed_report_date, network=network
                    ).first()

                    current_stock_item_for_price = Stock.query.filter_by(
                        network=network
                    ).first()
                    buying_price_for_virtual = Decimal("0.00")
                    if (
                        current_stock_item_for_price
                        and current_stock_item_for_price.buying_price_per_unit
                        is not None
                    ):
                        buying_price_for_virtual = (
                            current_stock_item_for_price.buying_price_per_unit
                        )

                    virtual_value_calculated = (
                        initial_balance * buying_price_for_virtual
                    )

                    if report:
                        app.logger.debug(
                            f"Updating seed report for {network.name} on {seed_report_date}."
                        )
                        report.initial_stock_balance = initial_balance
                        report.final_stock_balance = initial_balance  # For seed date, initial == final if no transactions
                        report.purchased_stock_amount = Decimal("0.00")
                        report.sold_stock_amount = Decimal("0.00")
                        report.virtual_value = virtual_value_calculated
                        report.debt_amount = Decimal("0.00")
                    else:
                        app.logger.debug(
                            f"Creating seed report for {network.name} on {seed_report_date}."
                        )
                        new_report = DailyStockReport(
                            report_date=seed_report_date,
                            network=network,
                            initial_stock_balance=initial_balance,
                            purchased_stock_amount=Decimal("0.00"),
                            sold_stock_amount=Decimal("0.00"),
                            final_stock_balance=initial_balance,
                            virtual_value=virtual_value_calculated,
                            debt_amount=Decimal("0.00"),
                        )
                        db.session.add(new_report)

                # --- Phase 3: Manual creation/update for DailyOverallReport for the seed date ---
                all_seeded_daily_reports = DailyStockReport.query.filter_by(
                    report_date=seed_report_date
                ).all()

                total_initial = sum(
                    r.initial_stock_balance for r in all_seeded_daily_reports
                )
                total_final = sum(
                    r.final_stock_balance for r in all_seeded_daily_reports
                )
                total_virtual = sum(r.virtual_value for r in all_seeded_daily_reports)
                total_debts_overall = Decimal("0.00")  # No debts for initial seed day

                overall_seed_report = DailyOverallReport.query.filter_by(
                    report_date=seed_report_date
                ).first()

                if overall_seed_report:
                    overall_seed_report.total_initial_stock = total_initial
                    overall_seed_report.total_final_stock = total_final
                    overall_seed_report.total_virtual_value = total_virtual
                    overall_seed_report.total_purchased_stock = Decimal("0.00")
                    overall_seed_report.total_sold_stock = Decimal("0.00")
                    overall_seed_report.total_debts = total_debts_overall
                    overall_seed_report.total_capital_circulant = total_virtual
                    overall_seed_report.total_sales_from_transactions = Decimal(
                        "0.00"
                    )  # No sales on seed day
                else:
                    overall_seed_report = DailyOverallReport(
                        report_date=seed_report_date,
                        total_initial_stock=total_initial,
                        total_purchased_stock=Decimal("0.00"),
                        total_sold_stock=Decimal("0.00"),
                        total_final_stock=total_final,
                        total_virtual_value=total_virtual,
                        total_debts=total_debts_overall,
                        total_capital_circulant=total_virtual,
                        total_sales_from_transactions=Decimal("0.00"),
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

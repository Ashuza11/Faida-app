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
from datetime import date, datetime, timedelta
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


def generate_daily_report(app, report_date_to_update=None):
    """
    Calculates and updates DailyStockReport and DailyOverallReport for a given date.
    This should be run daily, ideally after all transactions for the day are recorded.
    This function will be called by APScheduler.
    """
    with app.app_context():  # Ensure context when called from scheduler or CLI
        if report_date_to_update is None:
            report_date_to_update = date.today()

        app.logger.info(
            f"Generating/Updating daily reports for {report_date_to_update}"
        )

        try:
            # --- Step 1: Calculate daily purchases and sales from actual transactions ---
            daily_purchases = (
                db.session.query(
                    StockPurchase.network,
                    func.sum(StockPurchase.amount_purchased).label(
                        "total_purchased_amount"
                    ),
                )
                .filter(cast(StockPurchase.created_at, Date) == report_date_to_update)
                .group_by(StockPurchase.network)
                .all()
            )

            daily_sales = (
                db.session.query(
                    SaleItem.network,
                    func.sum(SaleItem.quantity).label("total_sold_amount"),
                )
                .join(Sale)
                .filter(cast(Sale.created_at, Date) == report_date_to_update)
                .group_by(SaleItem.network)
                .all()
            )

            purchases_by_network = {
                p.network: Decimal(str(p.total_purchased_amount or 0))
                for p in daily_purchases
            }
            sales_by_network = {
                s.network: Decimal(str(s.total_sold_amount or 0)) for s in daily_sales
            }

            # --- Step 2: Iterate through networks to update/create DailyStockReport entries ---
            total_initial_stock_day_overall = Decimal("0.00")
            total_purchased_stock_day_overall = Decimal("0.00")
            total_sold_stock_day_overall = Decimal("0.00")
            total_final_stock_day_overall = Decimal("0.00")
            total_virtual_value_day_overall = Decimal("0.00")
            total_debts_day_overall = Decimal("0.00")

            previous_day = report_date_to_update - timedelta(days=1)
            previous_daily_reports = DailyStockReport.query.filter_by(
                report_date=previous_day
            ).all()
            previous_final_stocks = {
                r.network: r.final_stock_balance for r in previous_daily_reports
            }

            networks = list(NetworkType.__members__.values())

            for network in networks:
                purchased_today = purchases_by_network.get(network, Decimal("0.00"))
                sold_today = sales_by_network.get(network, Decimal("0.00"))

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

                initial_stock_for_today = previous_final_stocks.get(network, None)
                if initial_stock_for_today is None:
                    # Fallback to live stock if no previous report exists (e.g., first day of app)
                    live_stock_item = Stock.query.filter_by(network=network).first()
                    initial_stock_for_today = (
                        live_stock_item.balance if live_stock_item else Decimal("0.00")
                    )
                    app.logger.warning(
                        f"No previous day report for {network.name} on {previous_day}. Using live stock as initial: {initial_stock_for_today}"
                    )

                daily_report.initial_stock_balance = initial_stock_for_today
                daily_report.purchased_stock_amount = purchased_today
                daily_report.sold_stock_amount = sold_today
                daily_report.final_stock_balance = (
                    initial_stock_for_today + purchased_today - sold_today
                )

                current_stock_item = Stock.query.filter_by(network=network).first()
                selling_price_per_unit = (
                    current_stock_item.selling_price_per_unit
                    if current_stock_item
                    else Decimal("1.00")
                )
                daily_report.virtual_value = (
                    daily_report.final_stock_balance * selling_price_per_unit
                )

                # Debts: This calculation is for debts incurred *up to and including* the report_date_to_update.
                network_debts_current = db.session.query(
                    func.sum(Sale.debt_amount)
                ).join(SaleItem).filter(
                    SaleItem.network == network,
                    Sale.debt_amount > 0,
                    # Ensure the sale happened on or before the report date
                    cast(Sale.created_at, Date) <= report_date_to_update,
                ).scalar() or Decimal(
                    "0.00"
                )
                daily_report.debt_amount = network_debts_current

                total_initial_stock_day_overall += daily_report.initial_stock_balance
                total_purchased_stock_day_overall += daily_report.purchased_stock_amount
                total_sold_stock_day_overall += daily_report.sold_stock_amount
                total_final_stock_day_overall += daily_report.final_stock_balance
                total_virtual_value_day_overall += daily_report.virtual_value
                total_debts_day_overall += daily_report.debt_amount

            # --- Step 3: Update/Create DailyOverallReport ---
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
            overall_report.total_debts = total_debts_day_overall
            overall_report.total_capital_circulant = (
                total_virtual_value_day_overall - total_debts_day_overall
            )

            db.session.commit()
            app.logger.info(
                f"Daily reports for {report_date_to_update} updated successfully."
            )

        except Exception as e:
            app.logger.error(
                f"Error generating daily reports for {report_date_to_update}: {e}"
            )
            db.session.rollback()
            raise
    """Generates a daily stock report for all networks.
    If report_date is None, it defaults to yesterday's date.
    This function calculates the stock balances, purchases, sales, and virtual values
    for each network type and stores them in the DailyStockReport and DailyOverallReport tables.
    """
    if report_date is None:
        report_date = date.today() - timedelta(days=1)
    app.logger.info(f"Generating daily stock report for {report_date}")

    with app.app_context():
        # --- PHASE 1: Clean existing data for this report_date ---
        try:
            app.logger.debug(
                f"Attempting to delete existing reports for {report_date}..."
            )
            DailyStockReport.query.filter_by(report_date=report_date).delete()
            DailyOverallReport.query.filter_by(report_date=report_date).delete()
            db.session.commit()  # Commit these deletions immediately
            app.logger.debug(
                f"Successfully deleted existing reports for {report_date}."
            )
        except Exception as e:
            app.logger.error(f"Error during deletion of reports for {report_date}: {e}")
            db.session.rollback()  # Rollback on error
            raise  # Re-raise the exception if deletion fails critically

        # --- PHASE 2: Generate new reports within a no_autoflush block ---
        # This prevents SQLAlchemy from trying to flush pending `db.session.add()`
        # calls prematurely when subsequent queries are made within the same session.
        with db.session.no_autoflush:
            temp_grand_totals = {
                "initial_stock": Decimal("0.00"),
                "purchased_stock": Decimal("0.00"),
                "sold_stock": Decimal("0.00"),
                "final_stock": Decimal("0.00"),
                "virtual_value": Decimal("0.00"),
                "total_debts": Decimal("0.00"),
                "total_sales_from_transactions": Decimal("0.00"),
            }

            start_of_report_day = datetime.combine(report_date, datetime.min.time())
            end_of_report_day = datetime.combine(report_date, datetime.max.time())

            for network in NetworkType:
                # --- Per-Network DailyStockReport Calculation ---
                network_name = network.name
                app.logger.debug(f"Calculating for network: {network_name}")

                # Get the initial stock balance from the previous day's final balance
                # If no previous report exists, this will be 0.00.
                previous_day_report = DailyStockReport.query.filter_by(
                    report_date=report_date - timedelta(days=1), network=network
                ).first()

                initial_stock_balance = Decimal("0.00")
                if (
                    previous_day_report
                    and previous_day_report.final_stock_balance is not None
                ):
                    initial_stock_balance = previous_day_report.final_stock_balance

                # Sum purchases for the current day for this network
                purchases_on_day = db.session.query(
                    func.sum(StockPurchase.amount_purchased)
                ).filter(
                    StockPurchase.network == network,
                    StockPurchase.created_at >= start_of_report_day,
                    StockPurchase.created_at <= end_of_report_day,
                ).scalar() or Decimal(
                    "0.00"
                )

                # Sum sales for the current day for this network
                sales_on_day = db.session.query(func.sum(SaleItem.quantity)).filter(
                    SaleItem.network == network,
                    SaleItem.created_at >= start_of_report_day,
                    SaleItem.created_at <= end_of_report_day,
                ).scalar() or Decimal("0.00")

                # Get current stock balance from the 'Stock' table
                current_stock_item = Stock.query.filter_by(network=network).first()

                final_stock_balance = Decimal("0.00")
                buying_price = Decimal("0.00")

                if current_stock_item:
                    final_stock_balance = current_stock_item.balance or Decimal("0.00")
                    buying_price = current_stock_item.buying_price_per_unit or Decimal(
                        "0.00"
                    )

                virtual_value = final_stock_balance * buying_price

                # Check if a report for this network and date already exists
                # (This path should ideally not be hit after a successful deletion above)
                daily_report_entry = DailyStockReport.query.filter_by(
                    report_date=report_date, network=network
                ).first()

                if daily_report_entry:
                    # Update existing report (should only happen if deletion failed or was skipped)
                    app.logger.warning(
                        f"    Existing DailyStockReport found unexpectedly for {network_name} on {report_date}. Updating instead of creating."
                    )
                    daily_report_entry.initial_stock_balance = initial_stock_balance
                    daily_report_entry.purchased_stock_amount = purchases_on_day
                    daily_report_entry.sold_stock_amount = sales_on_day
                    daily_report_entry.final_stock_balance = final_stock_balance
                    daily_report_entry.virtual_value = virtual_value
                else:
                    # Create new report
                    app.logger.debug(
                        f"    Creating DailyStockReport for {network_name} on {report_date}"
                    )
                    daily_report_entry = DailyStockReport(
                        report_date=report_date,
                        network=network,
                        initial_stock_balance=initial_stock_balance,
                        purchased_stock_amount=purchases_on_day,
                        sold_stock_amount=sales_on_day,
                        final_stock_balance=final_stock_balance,
                        virtual_value=virtual_value,
                    )
                    db.session.add(
                        daily_report_entry
                    )  # This add is queued by no_autoflush

                # Accumulate totals for DailyOverallReport
                temp_grand_totals["initial_stock"] += initial_stock_balance
                temp_grand_totals["purchased_stock"] += purchases_on_day
                temp_grand_totals["sold_stock"] += sales_on_day
                temp_grand_totals["final_stock"] += final_stock_balance
                temp_grand_totals["virtual_value"] += virtual_value
                temp_grand_totals["total_sales_from_transactions"] += sales_on_day

            # --- DailyOverallReport Calculation ---
            total_debts_in_period = db.session.query(func.sum(Sale.debt_amount)).filter(
                Sale.created_at >= start_of_report_day,
                Sale.created_at <= end_of_report_day,
                Sale.debt_amount > Decimal("0.00"),
            ).scalar() or Decimal("0.00")
            temp_grand_totals["total_debts"] = total_debts_in_period

            capital_circulant = (
                temp_grand_totals["total_debts"]
                + temp_grand_totals["virtual_value"]
                + temp_grand_totals["sold_stock"]
            )

            # Check if an overall report for this date already exists
            # (This path should ideally not be hit after a successful deletion above)
            overall_report_entry = DailyOverallReport.query.filter_by(
                report_date=report_date
            ).first()

            if overall_report_entry:
                # Update existing overall report
                app.logger.warning(
                    f"  Existing DailyOverallReport found unexpectedly for {report_date}. Updating instead of creating."
                )
                overall_report_entry.total_initial_stock = temp_grand_totals[
                    "initial_stock"
                ]
                overall_report_entry.total_purchased_stock = temp_grand_totals[
                    "purchased_stock"
                ]
                overall_report_entry.total_sold_stock = temp_grand_totals[
                    "total_sales_from_transactions"
                ]
                overall_report_entry.total_final_stock = temp_grand_totals[
                    "final_stock"
                ]
                overall_report_entry.total_virtual_value = temp_grand_totals[
                    "virtual_value"
                ]
                overall_report_entry.total_debts = temp_grand_totals["total_debts"]
                overall_report_entry.total_capital_circulant = capital_circulant
            else:
                # Create new overall report
                app.logger.debug(f"  Creating DailyOverallReport for {report_date}")
                overall_report_entry = DailyOverallReport(
                    report_date=report_date,
                    total_initial_stock=temp_grand_totals["initial_stock"],
                    total_purchased_stock=temp_grand_totals["purchased_stock"],
                    total_sold_stock=temp_grand_totals["sold_stock"],
                    total_final_stock=temp_grand_totals["final_stock"],
                    total_virtual_value=temp_grand_totals["virtual_value"],
                    total_debts=temp_grand_totals["total_debts"],
                    total_capital_circulant=capital_circulant,
                )
                db.session.add(overall_report_entry)  # This add is queued

        # --- PHASE 3: Final Commit ---
        # All changes queued within the `no_autoflush` block are committed here.
        try:
            db.session.commit()
            app.logger.info(f"Daily report for {report_date} generated successfully.")
        except Exception as e:
            app.logger.error(
                f"Error during final commit of reports for {report_date}: {e}"
            )
            db.session.rollback()  # Rollback on error
            raise  # Re-raise the exception if final commit fails

    return True

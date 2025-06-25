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


def generate_daily_report(app, report_date=None):
    """Generates a daily stock report for all networks.
    If report_date is None, it defaults to yesterday's date.
    This function calculates the stock balances, purchases, sales, and virtual values
    for each network type and stores them in the DailyStockReport and DailyOverallReport tables.
    """
    if report_date is None:
        report_date = date.today() - timedelta(days=1)  # Default to yesterday

    app.logger.info(f"Generating daily stock report for {report_date}")

    # Remove existing reports for this date to prevent unique constraint errors during regeneration
    # This is often done for regeneration, but you could also update in place.
    # For initial setup and debugging, this is safer.
    with app.app_context():
        # Ensure we delete both DailyStockReport and DailyOverallReport for the specific date
        # if you intend to completely regenerate.
        # This part is critical for avoiding the UNIQUE constraint error if running multiple times for the same day.
        DailyStockReport.query.filter_by(report_date=report_date).delete()
        DailyOverallReport.query.filter_by(report_date=report_date).delete()
        db.session.commit()  # Commit the deletions immediately

        temp_grand_totals = {
            "initial_stock": Decimal("0.00"),
            "purchased_stock": Decimal("0.00"),
            "sold_stock": Decimal("0.00"),
            "final_stock": Decimal("0.00"),
            "virtual_value": Decimal("0.00"),
            "total_debts": Decimal("0.00"),
            "total_sales_from_transactions": Decimal("0.00"),
        }

        # Calculate start and end of the reporting day
        start_of_report_day = datetime.combine(report_date, datetime.min.time())
        end_of_report_day = datetime.combine(report_date, datetime.max.time())

        for network in NetworkType:
            # --- Per-Network DailyStockReport Calculation ---
            network_name = network.name
            app.logger.debug(f"  Calculating for network: {network_name}")

            # Get the initial stock balance from the previous day's final balance
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
            daily_report_entry = DailyStockReport.query.filter_by(
                report_date=report_date, network=network
            ).first()

            if daily_report_entry:
                # Update existing report
                app.logger.debug(
                    f"    Updating DailyStockReport for {network_name} on {report_date}"
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
                db.session.add(daily_report_entry)

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
            + temp_grand_totals[
                "sold_stock"
            ]  # Note: this sum might need review for exact definition of capital_circulant
        )

        # Check if an overall report for this date already exists
        overall_report_entry = DailyOverallReport.query.filter_by(
            report_date=report_date
        ).first()

        if overall_report_entry:
            # Update existing overall report
            app.logger.debug(f"  Updating DailyOverallReport for {report_date}")
            overall_report_entry.total_initial_stock = temp_grand_totals[
                "initial_stock"
            ]
            overall_report_entry.total_purchased_stock = temp_grand_totals[
                "purchased_stock"
            ]
            overall_report_entry.total_sold_stock = temp_grand_totals["sold_stock"]
            overall_report_entry.total_final_stock = temp_grand_totals["final_stock"]
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
            db.session.add(overall_report_entry)

        # Commit all changes for the day at once
        db.session.commit()
        app.logger.info(f"Daily report for {report_date} generated successfully.")

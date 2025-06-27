from apps import db
from apps.authentication.models import (
    DailyStockReport,
    DailyOverallReport,
    NetworkType,
    Stock,
    StockPurchase,
    Sale,
    SaleItem,
)
from decimal import Decimal
from datetime import date, datetime, timedelta
from flask import Flask, current_app  # current_app is good for logging within context
from sqlalchemy import func, cast, Date, and_


def seed_initial_stock_balances(app):
    """
    Seeds initial DailyStockReport entries for a specific historical date (e.g., Day 0)
    to provide a starting point for 'initial_stock_balance' for subsequent reports.
    Also ensures the live Stock table has corresponding initial balances.
    """
    # Define the date for the "Day 0" report
    # This report's final_stock_balance will become Day 1's initial_stock_balance
    seed_report_date = date(
        2025, 6, 26
    )  # IMPORTANT: Set this to *yesterday* or a past date
    # if you want today's report to be based on this seed.
    # If you set it to today, today's initial stock will be derived from it.

    initial_balances_for_seed = {
        NetworkType.AIRTEL: Decimal("11731.00"),
        NetworkType.ORANGE: Decimal("4694.00"),
        NetworkType.VODACOM: Decimal("8533.00"),
        NetworkType.AFRICEL: Decimal("4073.00"),
    }

    with app.app_context():  # Ensure we are in application context
        app.logger.info(
            f"Seeding initial DailyStockReport for {seed_report_date} and Stock table."
        )

        try:
            # Using db.session.no_autoflush can be good for complex updates,
            # but for simple adds/updates, it might not be strictly necessary
            # if you commit at the end. Keep it if it helps your logic.
            with db.session.no_autoflush:
                # --- Phase 1: Ensure the live Stock table has corresponding initial balances ---
                # This ensures your 'live' stock figures are aligned with the seed data.
                for network, balance in initial_balances_for_seed.items():
                    stock_item = Stock.query.filter_by(network=network).first()
                    if stock_item:
                        stock_item.balance = balance
                        # If you also have buying_price_per_unit or selling_price_per_unit
                        # as updateable fields, ensure they are also Decimal.
                        # For example:
                        # stock_item.buying_price_per_unit = Decimal("0.95")
                        # stock_item.selling_price_per_unit = Decimal("1.00")
                        app.logger.debug(
                            f"Updated live Stock balance for {network.name} to {balance}."
                        )
                    else:
                        new_stock_item = Stock(
                            network=network,
                            balance=balance,
                            buying_price_per_unit=Decimal("0.95"),  # Example default
                            selling_price_per_unit=Decimal("1.00"),  # Example default
                        )
                        db.session.add(new_stock_item)
                        app.logger.debug(
                            f"Created live Stock item for {network.name} with balance {balance}."
                        )

                # --- Phase 2: Create/Update the DailyStockReport for the seed_report_date ---
                # This creates a historical record of stock at the seed_report_date.
                for network, initial_balance in initial_balances_for_seed.items():
                    report = DailyStockReport.query.filter_by(
                        report_date=seed_report_date, network=network
                    ).first()

                    # Fetch current buying price from live Stock for virtual_value calculation
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
                # Aggregate values from DailyStockReport entries for the seed date
                all_seeded_daily_reports = DailyStockReport.query.filter_by(
                    report_date=seed_report_date
                ).all()

                # Summing values which are already Decimals from the report objects
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
                    overall_seed_report.total_capital_circulant = total_virtual  # Assuming virtual value is capital circulant for seed
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
                    )
                    db.session.add(overall_seed_report)

            db.session.commit()  # Commit all changes at once
            app.logger.info(
                f"Initial stock report and live stock for {seed_report_date} seeded successfully."
            )

        except Exception as e:
            app.logger.error(f"Error seeding initial report data: {e}")
            db.session.rollback()  # Rollback on error
            raise  # Re-raise to see the error


# This function might live in apps.home.utils.py or similar
# I'll include it here for completeness of your provided code,
# but it's generally better organized in a utils file.
def update_daily_reports(app, report_date_to_update=None):
    """
    Calculates and updates DailyStockReport and DailyOverallReport for a given date.
    This should be run daily, ideally after all transactions for the day are recorded.
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
                    func.sum(SaleItem.quantity).label(
                        "total_sold_amount"
                    ),  # SaleItem.quantity is the amount sold
                )
                .join(Sale)  # Ensure join if SaleItem is linked to Sale for created_at
                .filter(
                    cast(Sale.created_at, Date) == report_date_to_update
                )  # Filter by Sale.created_at
                .group_by(SaleItem.network)
                .all()
            )

            # Convert to dictionaries for easy lookup, ensure values are Decimal
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

            # Get previous day's final stock for initial calculation
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

                # Determine initial stock balance for *this* report_date_to_update
                # It's the final stock balance of the previous day, or the live stock balance if no previous report
                initial_stock_for_today = previous_final_stocks.get(network, None)
                if initial_stock_for_today is None:
                    # Fallback to live stock if no previous report exists (e.g., first run after seed)
                    live_stock_item = Stock.query.filter_by(network=network).first()
                    initial_stock_for_today = (
                        live_stock_item.balance if live_stock_item else Decimal("0.00")
                    )
                    app.logger.warning(
                        f"No previous day report for {network.name}. Using live stock as initial: {initial_stock_for_today}"
                    )

                daily_report.initial_stock_balance = initial_stock_for_today
                daily_report.purchased_stock_amount = purchased_today
                daily_report.sold_stock_amount = sold_today
                daily_report.final_stock_balance = (
                    initial_stock_for_today + purchased_today - sold_today
                )

                # Calculate virtual value based on the final stock balance and current selling price
                # IMPORTANT: For historical reports, you might want to use the selling price *at that time*.
                # For simplicity here, we're using the current live selling price.
                # If you need historical selling prices, you'd need to store them in a history table.
                current_stock_item = Stock.query.filter_by(network=network).first()
                selling_price_per_unit = (
                    current_stock_item.selling_price_per_unit
                    if current_stock_item
                    else Decimal("1.00")
                )
                daily_report.virtual_value = (
                    daily_report.final_stock_balance * selling_price_per_unit
                )

                # Calculate current outstanding debts for the network (sum of debt_amount from UNPAID sales *up to this date*)
                # This query sums debts for sales where sale_items belong to this network and are unpaid.
                # If report_date_to_update is in the past, this needs to accurately reflect debts *at that past date*.
                # This is complex:
                #    - If it's today, sum all current unpaid debts for this network.
                #    - If it's historical, you'd ideally need a snapshot of debts per day.
                #      For simplicity, the current debt sum is being used here, which might not be historically accurate.
                #      A proper historical debt report would need a more complex model (e.g., debt history table).
                # For the daily report generation, we consider *new* debts incurred on this day, or total current debts.
                # The current implementation queries all sales for the day, which might not correctly capture *outstanding* debts.
                # Let's adjust to capture total outstanding debts associated with sales of this network.
                network_debts_for_day = db.session.query(
                    func.sum(Sale.debt_amount)
                ).join(SaleItem).filter(
                    SaleItem.network == network,
                    Sale.debt_amount > 0,  # Only consider actual debt
                    cast(Sale.created_at, Date)
                    <= report_date_to_update,  # Debts incurred up to and including this date
                ).scalar() or Decimal(
                    "0.00"
                )
                daily_report.debt_amount = (
                    network_debts_for_day  # Store the cumulative debt at end of day
                )

                # Accumulate for overall report
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
            # Capital circulant = Virtual Value - Debts (assuming debts reduce capital)
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
            raise  # Re-raise for debugging


# This function should probably be in apps.home.utils.py
def initialize_stock_items(app):
    """
    Ensures that all NetworkType enum members have a corresponding Stock entry.
    This is typically run once on app startup or as part of a setup script.
    """
    with app.app_context():
        app.logger.info(
            "Initializing stock items (ensuring all networks have a Stock entry)."
        )
        for network_type in NetworkType:
            existing_stock = Stock.query.filter_by(network=network_type).first()
            if not existing_stock:
                # Create a default stock entry for the network
                new_stock = Stock(
                    network=network_type,
                    balance=Decimal("0.00"),  # Start with zero or a small default
                    buying_price_per_unit=Decimal("0.95"),  # Default buying price
                    selling_price_per_unit=Decimal("1.00"),  # Default selling price
                )
                db.session.add(new_stock)
                app.logger.info(f"Created initial Stock entry for {network_type.name}.")
            else:
                app.logger.debug(f"Stock entry for {network_type.name} already exists.")
        db.session.commit()
        app.logger.info("Stock item initialization complete.")


# Alias for scheduler usage (if generate_daily_report is in utils)
# This is generally defined in the file where the function actually lives
# For clarity, if update_daily_reports is the main function for scheduler,
# rename it to generate_daily_report or ensure the scheduler calls the correct one.
# For now, let's assume update_daily_reports IS generate_daily_report for the scheduler.
generate_daily_report = (
    update_daily_reports  # This line might live in utils.py if functions are split
)

import click
from flask.cli import with_appcontext
from datetime import datetime, timedelta, date
from decimal import Decimal
from flask import current_app
from sqlalchemy import select  # Import select for SQLAlchemy 2.0 style queries


# Only import utility functions that don't depend on 'db' at the global level.
# NOTE: If your utility functions (seed_initial_stock_balances, etc.)
# also import 'from apps import db', you'll need to modify them to accept
# 'current_app' and use 'from flask import current_app' to get the database
# object *inside* the utility function.
# Based on the previous solution, they should be designed to accept `app`
# or use `current_app`, which is good.

from apps.main.utils import (
    seed_initial_stock_balances,
    update_daily_reports,
    initialize_stock_items,
)
from apps.auth.utils import create_superadmin

# Keep model imports only if they don't depend on db/app context being initialized
# For safety, let's move the models inside the simulate-transactions command.


def register_cli_commands(app):
    """
    Registers custom commands with the Flask CLI under the 'setup' group.
    This function should be called inside your create_app() function.
    """

    @app.cli.group()
    def setup():
        """Application setup, data initialization, and report generation commands."""
        pass

    # --- Database & Setup Commands ---

    @setup.command("init-db")
    @with_appcontext
    def init_db_command():
        """Creates database tables from models."""
        # IMPORT DB LOCALLY: db is now imported from current_app's context
        from apps import db

        db.create_all()
        click.echo("Initialized the database.")

    @setup.command("create-superadmin")
    @with_appcontext
    def create_superadmin_command():
        """Creates the initial superadmin user if one doesn't exist."""
        # create_superadmin utility function should handle context internally.
        if create_superadmin():
            click.echo("Superadmin created successfully.")
        else:
            click.echo("Superadmin already exists or an error occurred.")

    @setup.command("init-stock")
    @with_appcontext
    def init_stock_command():
        """Initializes stock items for all network types."""
        # utility function uses current_app, which is fine
        initialize_stock_items(current_app)
        click.echo("Stock items initialized.")

    # --- Data & Reporting Commands ---

    @setup.command("seed-reports")
    @with_appcontext
    @click.option(
        "--date",
        "date_str",
        default=None,
        help="Optional seed date (YYYY-MM-DD). Defaults to 2 days ago.",
    )
    def seed_reports_command(date_str):
        """Seeds initial stock balances for a specific date."""
        if date_str:
            try:
                seed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                click.echo("Invalid date format. Please use YYYY-MM-DD.")
                return
        else:
            seed_date = date.today() - timedelta(days=2)

        click.echo(f"Attempting to seed reports for {seed_date}...")
        try:
            seed_initial_stock_balances(current_app, seed_date)
            click.echo(f"Successfully seeded reports for {seed_date}.")
        except Exception as e:
            click.echo(f"Failed to seed reports for {seed_date}: {e}")
            current_app.logger.error(f"Seed reports failed: {e}", exc_info=True)

    @setup.command("generate-reports")
    @with_appcontext
    @click.option(
        "--date",
        default=None,
        help="Date for report (YYYY-MM-DD). Defaults to yesterday.",
    )
    def generate_reports_command(date):
        """Generates/updates daily reports for a given date."""
        if date:
            try:
                report_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                click.echo("Invalid date format. Please use YYYY-MM-DD.")
                return
        else:
            report_date = date.today() - timedelta(days=1)

        click.echo(f"Generating reports for {report_date}...")
        try:
            update_daily_reports(current_app, report_date_to_update=report_date)
            click.echo(f"Reports for {report_date} generated successfully.")
        except Exception as e:
            click.echo(f"Failed to generate reports for {report_date}: {e}")
            current_app.logger.error(f"Generate reports failed: {e}", exc_info=True)

    @setup.command("simulate-transactions")
    @with_appcontext
    @click.option(
        "--date",
        default=None,
        help="Date for simulation (YYYY-MM-DD). Defaults to today.",
    )
    @click.option(
        "--purchases",
        default=100,
        type=int,
        help="Amount of stock to purchase per network.",
    )
    @click.option(
        "--sales", default=50, type=int, help="Amount of stock to sell per network."
    )
    def simulate_transactions_command(date_str, purchases, sales):
        """Simulates stock purchases and sales for a given date."""
        # IMPORT ALL DEPENDENCIES LOCALLY
        from apps import db  # Get the db object
        from apps.models import (
            NetworkType,
            User,
            Stock,
            StockPurchase,
            Sale,
            SaleItem,
        )  # Get the models

        if date_str:
            try:
                transaction_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                click.echo("Invalid date format. Please use YYYY-MM-DD.")
                return
        else:
            transaction_date = date.today()

        click.echo(f"Simulating transactions for {transaction_date}...")

        networks = list(NetworkType.__members__.values())

        # Use SQLAlchemy 2.0 select method
        user = db.session.execute(select(User)).scalar()

        if not user:
            click.echo("Error: No user found. Please create a user first.")
            return

        for network in networks:
            stock_item = db.session.execute(
                select(Stock).filter_by(network=network)
            ).scalar()
            if not stock_item:
                click.echo(f"Warning: Stock for {network.name} not found. Skipping.")
                continue

            # Simulate Purchase
            new_purchase = StockPurchase(
                stock_item_id=stock_item.id,
                network=network,
                buying_price_at_purchase=stock_item.buying_price_per_unit,
                selling_price_at_purchase=stock_item.selling_price_per_unit,
                amount_purchased=purchases,
                purchased_by=user,
                # Ensure created_at is timezone-aware if your model expects it
                created_at=datetime.combine(transaction_date, datetime.now().time()),
            )
            db.session.add(new_purchase)
            stock_item.balance += purchases
            click.echo(
                f"  {network.name}: Purchased {purchases}. New balance: {stock_item.balance}"
            )

            # Simulate Sale
            if stock_item.balance >= sales:
                total_sale_amount = Decimal(sales) * stock_item.selling_price_per_unit
                new_sale = Sale(
                    vendeur=user,
                    total_amount=total_sale_amount,
                    amount_paid=total_sale_amount,
                    debt_amount=Decimal("0.00"),
                    created_at=datetime.combine(
                        transaction_date, datetime.now().time()
                    ),
                )
                db.session.add(new_sale)
                db.session.flush()

                new_sale_item = SaleItem(
                    sale=new_sale,
                    stock_item=stock_item,
                    network=network,
                    quantity=sales,
                    price_per_unit_applied=stock_item.selling_price_per_unit,
                    subtotal=total_sale_amount,
                )
                db.session.add(new_sale_item)
                stock_item.balance -= sales
                click.echo(
                    f" {network.name}: Sold {sales}. New balance: {stock_item.balance}"
                )
            else:
                click.echo(f" {network.name}: Not enough stock to sell. Skipping sale.")

        db.session.commit()
        click.echo("Transaction simulation complete.")


# --- End of register_cli_commands function ---

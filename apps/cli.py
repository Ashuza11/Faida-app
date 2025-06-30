import click
from . import db
import logging
from decimal import Decimal
from .config import Config
from flask import Flask
from datetime import date, timedelta, datetime, time
from .authentication.models import (
    NetworkType,
    User,
    StockPurchase,
    Sale,
    SaleItem,
)
from .home.utils import (
    seed_initial_stock_balances,
    update_daily_reports,
)

cli_logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def create_app_cli():
    """
    Creates and configures the Flask application for CLI commands.
    """
    app = Flask(__name__)
    app.config.from_object(Config)

    # Use the main app's logger for CLI too
    app.logger.setLevel(logging.INFO)
    db.init_app(app)

    with app.app_context():
        db.create_all()

    # --- CLI Commands Registration ---

    @app.cli.command("seed-reports")
    @click.option(
        "--date",
        default=None,
        help="Optional seed date (YYYY-MM-DD). Defaults to today - 2 days.",
    )
    def seed_reports_command(date):
        """Seeds initial stock balances for a specific date."""
        if date:
            try:
                seed_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                click.echo("Invalid date format. Please use YYYY-MM-DD.")
                return
        else:
            # Current date is June 29, 2025. Today - 2 days means June 27, 2025.
            # This aligns with your initial seed date in utils.py before modification.
            seed_date = date.today() - timedelta(days=2)

        click.echo(f"Attempting to seed reports for {seed_date}...")
        try:
            # Now seed_initial_stock_balances accepts the seed_date
            seed_initial_stock_balances(app, seed_date)
            click.echo(f"Successfully seeded reports for {seed_date}.")
        except Exception as e:
            click.echo(f"Failed to seed reports for {seed_date}: {e}")
            cli_logger.error(f"Error seeding reports: {e}", exc_info=True)

    @app.cli.command("generate-reports")
    @click.option(
        "--date",
        default=None,
        help="Date for which to generate report (YYYY-MM-DD). Defaults to yesterday.",  # Changed default
    )
    def generate_reports_command(date):
        """Generates/updates daily stock and overall reports for a given date."""
        if date:
            try:
                report_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                click.echo("Invalid date format. Please use YYYY-MM-DD.")
                return
        else:
            # Default to yesterday for full day's data
            report_date = date.today() - timedelta(days=1)

        click.echo(f"Generating reports for {report_date}...")
        try:
            # update_daily_reports already takes app and report_date
            update_daily_reports(app, report_date)
            click.echo(f"Reports for {report_date} generated successfully.")
        except Exception as e:
            click.echo(f"Failed to generate reports for {report_date}: {e}")
            cli_logger.error(f"Error generating reports: {e}", exc_info=True)

    @app.cli.command("simulate-transactions")
    @click.option(
        "--date",
        default=None,
        help="Date for which to simulate transactions (YYYY-MM-DD). Defaults to today.",
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
    def simulate_transactions_command(date, purchases, sales):
        """Simulates stock purchases and sales for a given date."""
        if date:
            try:
                transaction_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                click.echo("Invalid date format. Please use YYYY-MM-DD.")
                return
        else:
            transaction_date = date.today()

        with app.app_context():
            click.echo(f"Simulating transactions for {transaction_date}...")
            networks = list(NetworkType.__members__.values())
            user = db.session.query(User).first()

            if not user:
                click.echo(
                    "Error: No user found to record transactions. Please create a user first."
                )
                return

            try:
                from authentication.models import Stock
            except ImportError:
                click.echo(
                    "Error: Could not import Stock model. Make sure it's defined in authentication.models."
                )
                return

            for network in networks:
                stock_item = Stock.query.filter_by(network=network).first()
                if not stock_item:
                    click.echo(
                        f"Warning: Stock item for {network.name} not found. Skipping transactions for this network."
                    )
                    continue

                # Simulate purchase
                new_purchase = StockPurchase(
                    stock_item_id=stock_item.id,
                    network=network,
                    buying_price_at_purchase=stock_item.buying_price_per_unit,
                    selling_price_at_purchase=stock_item.selling_price_per_unit,
                    amount_purchased=purchases,
                    purchased_by=user,
                    created_at=datetime.combine(
                        transaction_date,
                        datetime.now().time(),  # Use datetime.now().time() for local time
                    ),
                )
                db.session.add(new_purchase)
                stock_item.balance += purchases
                click.echo(
                    f"  {network.name}: Purchased {purchases} units. New live stock: {stock_item.balance}"
                )

                # Simulate sale
                if stock_item.balance >= sales:
                    new_sale = Sale(
                        vendeur=user,
                        client_id=None,
                        total_amount=Decimal(sales) * stock_item.selling_price_per_unit,
                        amount_paid=Decimal(sales) * stock_item.selling_price_per_unit,
                        debt_amount=Decimal("0.00"),
                        created_at=datetime.combine(
                            transaction_date,
                            datetime.now().time(),  # Use datetime.now().time() for local time
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
                        subtotal=Decimal(sales) * stock_item.selling_price_per_unit,
                    )
                    db.session.add(new_sale_item)
                    stock_item.balance -= sales
                    click.echo(
                        f"  {network.name}: Sold {sales} units. New live stock: {stock_item.balance}"
                    )
                else:
                    click.echo(
                        f"  {network.name}: Not enough stock to sell {sales} units. Skipping sale."
                    )

            db.session.commit()
            click.echo("Transaction simulation complete.")

    return app


# Exposing the app factory function for Flask CLI
# This assumes this file is named something like 'cli.py' or 'run.py'
# and FLASK_APP is set to this file.
cli_app = create_app_cli()

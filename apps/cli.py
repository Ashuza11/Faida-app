import click
from decimal import Decimal
from apps.config import Config
from flask import Flask
from apps.authentication.models import db, NetworkType, User
from apps.home.utils import (
    seed_initial_stock_balances,
    update_daily_reports,
)
from apps.authentication.models import (
    Stock,
    StockPurchase,
    Sale,
    SaleItem,
)
from datetime import date, timedelta, datetime


def create_app():
    """
    Creates and configures the Flask application for CLI commands.
    """
    app = Flask(__name__)
    app.config.from_object(Config)  # Load your application configuration

    # Initialize extensions and database
    # We'll use the db object initialized here for CLI commands.
    # Note: In a real application, you might want a more robust way to
    # manage app context for CLI, but for simple commands, this works.
    db.init_app(app)

    with app.app_context():
        # Ensure tables are created if they don't exist.
        # This is important for CLI commands that interact with the database.
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
            seed_date = date.today() - timedelta(days=2)  # Default seed date

        click.echo(f"Attempting to seed reports for {seed_date}...")
        try:
            # Pass app and seed_date if your seed_initial_stock_balances can accept it.
            # Based on your snippet, it currently only takes 'app'.
            # If you want dynamic seeding, you'll need to modify seed_initial_stock_balances
            # to accept a seed_date argument. For now, calling as it is.
            seed_initial_stock_balances(app)
            click.echo(f"Successfully attempted to seed reports for {seed_date}.")
        except Exception as e:
            click.echo(f"Failed to seed reports for {seed_date}: {e}")

    @app.cli.command("generate-reports")
    @click.option(
        "--date",
        default=None,
        help="Date for which to generate report (YYYY-MM-DD). Defaults to today.",
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
            report_date = date.today()

        click.echo(f"Generating reports for {report_date}...")
        try:
            update_daily_reports(app, report_date)
            click.echo(f"Reports for {report_date} generated successfully.")
        except Exception as e:
            click.echo(f"Failed to generate reports for {report_date}: {e}")

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
            user = db.session.query(
                User
            ).first()  # Assuming a User exists for purchase/sale recording

            if not user:
                click.echo(
                    "Error: No user found to record transactions. Please create a user first."
                )
                return

            # Dynamically import Stock model here to avoid circular dependencies
            # if Stock is defined in apps.home.models
            try:
                from apps.authentication.models import Stock
            except ImportError:
                click.echo(
                    "Error: Could not import Stock model. Make sure it's defined in apps.authentication.models."
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
                        transaction_date, datetime.utcnow().time()
                    ),  # Set time to simulate within day
                )
                db.session.add(new_purchase)
                stock_item.balance += purchases  # Update live stock
                click.echo(
                    f"  {network.name}: Purchased {purchases} units. New live stock: {stock_item.balance}"
                )

                # Simulate sale
                if stock_item.balance >= sales:
                    new_sale = Sale(
                        vendeur=user,
                        client_id=None,  # Adhoc client for simulation
                        total_amount=Decimal(sales) * stock_item.selling_price_per_unit,
                        amount_paid=Decimal(sales) * stock_item.selling_price_per_unit,
                        debt_amount=Decimal("0.00"),
                        created_at=datetime.combine(
                            transaction_date, datetime.utcnow().time()
                        ),
                    )
                    db.session.add(new_sale)
                    db.session.flush()  # Needed to get new_sale.id for SaleItem

                    new_sale_item = SaleItem(
                        sale=new_sale,
                        stock_item=stock_item,
                        network=network,
                        quantity=sales,
                        price_per_unit_applied=stock_item.selling_price_per_unit,
                        subtotal=Decimal(sales) * stock_item.selling_price_per_unit,
                    )
                    db.session.add(new_sale_item)
                    stock_item.balance -= sales  # Update live stock
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
if __name__ == "__main__":
    # This block is typically not needed for standard Flask CLI usage
    # where FLASK_APP is set to the module containing create_app().
    # It's more for direct execution, but Flask CLI handles app creation.
    pass

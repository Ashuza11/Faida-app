import click
from flask import Blueprint
from datetime import datetime, timedelta
from decimal import Decimal

from . import db
from .main.utils import (
    seed_initial_stock_balances,
    update_daily_reports,
    initialize_stock_items,
)
from .auth.utils import create_superadmin
from .models import NetworkType, User, Stock, StockPurchase, Sale, SaleItem

# Create a blueprint for CLI commands
# The 'cli_group=None' makes commands available directly under 'flask'
# e.g., 'flask seed-reports' instead of 'flask cli seed-reports'
cli_bp = Blueprint("cli", __name__, cli_group=None)

# --- Database & Setup Commands ---


@cli_bp.cli.command("init-db")
def init_db_command():
    """Creates database tables from models."""
    db.create_all()
    click.echo("Initialized the database.")


@cli_bp.cli.command("create-superadmin")
def create_superadmin_command():
    """Creates the initial superadmin user if one doesn't exist."""
    if create_superadmin():
        click.echo("Superadmin created successfully.")
    else:
        click.echo("Superadmin already exists or an error occurred.")


@cli_bp.cli.command("init-stock")
def init_stock_command():
    """Initializes stock items for all network types."""
    initialize_stock_items()
    click.echo("Stock items initialized.")


# --- Data & Reporting Commands ---


@cli_bp.cli.command("seed-reports")
@click.option(
    "--date",
    default=None,
    help="Optional seed date (YYYY-MM-DD). Defaults to 2 days ago.",
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
        seed_date = datetime.today().date() - timedelta(days=2)

    click.echo(f"Attempting to seed reports for {seed_date}...")
    try:
        seed_initial_stock_balances(seed_date)
        click.echo(f"Successfully seeded reports for {seed_date}.")
    except Exception as e:
        click.echo(f"Failed to seed reports for {seed_date}: {e}")


@cli_bp.cli.command("generate-reports")
@click.option(
    "--date", default=None, help="Date for report (YYYY-MM-DD). Defaults to yesterday."
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
        report_date = datetime.today().date() - timedelta(days=1)

    click.echo(f"Generating reports for {report_date}...")
    try:
        update_daily_reports(report_date)
        click.echo(f"Reports for {report_date} generated successfully.")
    except Exception as e:
        click.echo(f"Failed to generate reports for {report_date}: {e}")


@cli_bp.cli.command("simulate-transactions")
@click.option(
    "--date", default=None, help="Date for simulation (YYYY-MM-DD). Defaults to today."
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
        transaction_date = datetime.today().date()

    click.echo(f"Simulating transactions for {transaction_date}...")
    # The rest of your simulation logic goes here...
    # (The logic from your original __init__.py is copied below)
    networks = list(NetworkType.__members__.values())
    user = db.session.query(User).first()

    if not user:
        click.echo("Error: No user found. Please create a user first.")
        return

    for network in networks:
        stock_item = Stock.query.filter_by(network=network).first()
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
            created_at=datetime.combine(transaction_date, datetime.now().time()),
        )
        db.session.add(new_purchase)
        stock_item.balance += purchases
        click.echo(
            f"  {network.name}: Purchased {purchases}. New balance: {stock_item.balance}"
        )

        # Simulate Sale
        if stock_item.balance >= sales:
            total_sale_amount = Decimal(sales) * stock_item.selling_price_per_unit
            new_sale = Sale(
                vendeur=user,
                total_amount=total_sale_amount,
                amount_paid=total_sale_amount,
                debt_amount=Decimal("0.00"),
                created_at=datetime.combine(transaction_date, datetime.now().time()),
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
                f"  {network.name}: Sold {sales}. New balance: {stock_item.balance}"
            )
        else:
            click.echo(f"  {network.name}: Not enough stock to sell. Skipping sale.")

    db.session.commit()
    click.echo("Transaction simulation complete.")

import os
from decouple import config
from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from importlib import import_module
from flask_apscheduler import APScheduler
from flask_migrate import Migrate
import logging
from datetime import date, datetime, timedelta
from apps.config import DebugConfig
import click

# Create extensions without importing models
db = SQLAlchemy()
login_manager = LoginManager()
scheduler = APScheduler()
migrate = Migrate()
app_logger = logging.getLogger(__name__)

# Basic logging config for the entire app, including CLI
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


def register_extensions(app):
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    from apps.authentication.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    login_manager.login_view = "authentication_blueprint.login"

    if os.environ.get("FLASK_RUNNING_MIGRATION") != "true":
        scheduler.init_app(app)
    else:
        app_logger.info("Skipping APScheduler initialization during migration.")


def register_blueprints(app):
    for module_name in ("authentication", "home"):
        module = import_module(f"apps.{module_name}.routes")
        app.register_blueprint(module.blueprint)


def configure_database(app):
    @app.teardown_request
    def shutdown_session(exception=None):
        db.session.remove()


# NEW FUNCTION: Register CLI Commands
def register_cli_commands(app):
    from apps.home.utils import (
        seed_initial_stock_balances,
        update_daily_reports,
    )
    from apps.authentication.models import (
        NetworkType,
        User,
        Stock,
        StockPurchase,
        Sale,
        SaleItem,
    )
    from decimal import Decimal

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
            seed_date = date.today() - timedelta(days=2)

        click.echo(f"Attempting to seed reports for {seed_date}...")
        try:
            with app.app_context():
                seed_initial_stock_balances(app, seed_date)
            click.echo(f"Successfully seeded reports for {seed_date}.")
        except Exception as e:
            click.echo(f"Failed to seed reports for {seed_date}: {e}")
            app_logger.error(f"Error seeding reports: {e}", exc_info=True)

    @app.cli.command("generate-reports")
    @click.option(
        "--date",
        default=None,
        help="Date for which to generate report (YYYY-MM-DD). Defaults to yesterday.",
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
            report_date = date.today() - timedelta(days=1)

        click.echo(f"Generating reports for {report_date}...")
        try:
            with app.app_context():  # Ensure app context is active for db operations
                update_daily_reports(app, report_date)
            click.echo(f"Reports for {report_date} generated successfully.")
        except Exception as e:
            click.echo(f"Failed to generate reports for {report_date}: {e}")
            app_logger.error(f"Error generating reports: {e}", exc_info=True)

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

            for network in networks:
                stock_item = Stock.query.filter_by(network=network).first()
                if not stock_item:
                    click.echo(
                        f"Warning: Stock item for {network.name} not found. Skipping transactions for this network."
                    )
                    continue

                new_purchase = StockPurchase(
                    stock_item_id=stock_item.id,
                    network=network,
                    buying_price_at_purchase=stock_item.buying_price_per_unit,
                    selling_price_at_purchase=stock_item.selling_price_per_unit,
                    amount_purchased=purchases,
                    purchased_by=user,
                    created_at=datetime.combine(
                        transaction_date, datetime.now().time()
                    ),
                )
                db.session.add(new_purchase)
                stock_item.balance += purchases
                click.echo(
                    f"  {network.name}: Purchased {purchases} units. New live stock: {stock_item.balance}"
                )

                if stock_item.balance >= sales:
                    new_sale = Sale(
                        vendeur=user,
                        client_id=None,
                        total_amount=Decimal(sales) * stock_item.selling_price_per_unit,
                        amount_paid=Decimal(sales) * stock_item.selling_price_per_unit,
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


def create_app(config_object=DebugConfig):
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.logger.setLevel(logging.INFO)

    register_extensions(app)
    register_blueprints(app)
    configure_database(app)
    register_cli_commands(app)

    with app.app_context():
        db.create_all()
        app_logger.info("Ensured database tables are created.")

        from apps.authentication.models import User, RoleType
        from apps.authentication.util import create_superadmin
        from apps.home.utils import initialize_stock_items, update_daily_reports
        from apps.errors import register_error_handlers

        register_error_handlers(app, db)
        app_logger.info("Error handlers registered.")

        initialize_stock_items(app)
        app_logger.info("Stock items initialized.")

        if os.environ.get("FLASK_RUNNING_MIGRATION") != "true":
            if app.config.get("SCHEDULER_API_ENABLED"):
                if not scheduler.running:
                    try:
                        scheduler.start()
                        app_logger.info("APScheduler started.")
                    except Exception as e:
                        app_logger.error(f"Error starting APScheduler: {e}")
                else:
                    app_logger.info("APScheduler already running.")

                if not app.config.get("DEBUG", False):
                    if not scheduler.get_job("daily_report_gen"):
                        app_logger.info("Scheduling daily report generation job...")
                        scheduler.add_job(
                            id="daily_report_gen",
                            func=update_daily_reports,
                            trigger="cron",
                            hour=0,
                            minute=15,
                            args=[app],
                            replace_existing=True,
                            misfire_grace_time=3600,
                        )
                        app_logger.info("Daily report generation job scheduled.")
                    else:
                        app_logger.info("Daily report generation job already exists.")
                else:
                    app_logger.info(
                        "Daily report generation job NOT scheduled in DEBUG mode. Consider running manually or for specific tests."
                    )
            else:
                app_logger.info("Scheduler API not enabled, skipping job scheduling.")
        else:
            app_logger.info("Skipping job scheduling during migration.")

        try:
            if not User.query.filter_by(role=RoleType.SUPERADMIN).first():
                if create_superadmin():
                    app_logger.info("Superadmin created successfully.")
                else:
                    app_logger.warning(
                        "Superadmin creation attempted but no superadmin found after."
                    )
            else:
                app_logger.info("Superadmin already exists, skipping creation.")
        except Exception as e:
            app_logger.error(f"Error during superadmin creation: {e}", exc_info=True)

    return app

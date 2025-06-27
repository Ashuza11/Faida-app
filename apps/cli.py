import click
from flask.cli import with_appcontext
from apps import db
from apps.home.seed_data import (
    seed_initial_stock_balances,
)


@click.command("seed-db")
@with_appcontext
def seed_db_command():
    """Seeds the database with initial data including historical reports and live stock."""
    click.echo("Attempting to seed the database...")
    from flask import (
        current_app,
    )

    try:
        seed_initial_stock_balances(current_app)
        click.echo("Database seeded successfully!")
    except Exception as e:
        click.echo(f"Error seeding database: {e}", err=True)
        current_app.logger.error(f"Error during seed_db command: {e}")


@click.command("generate-report")
@click.option(
    "--date",
    default=None,
    help="Date for report generation (YYYY-MM-DD). Defaults to today.",
)
@with_appcontext
def generate_report_command(date):
    """Manually triggers daily report generation for a specific date or today."""
    from flask import current_app
    from datetime import datetime
    from apps.home.utils import generate_daily_report

    report_date = None
    if date:
        try:
            report_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            click.echo("Invalid date format. Use YYYY-MM-DD.", err=True)
            return

    click.echo(f'Generating daily report for {report_date or "today"}...')
    try:
        generate_daily_report(current_app, report_date)
        click.echo(f'Daily report for {report_date or "today"} generated successfully!')
    except Exception as e:
        click.echo(f"Error generating report: {e}", err=True)
        current_app.logger.error(f"Error during generate_report command: {e}")

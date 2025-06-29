from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from importlib import import_module
from flask_apscheduler import APScheduler
from flask_migrate import Migrate
import os
import logging

# Create extensions without importing models
db = SQLAlchemy()
login_manager = LoginManager()
scheduler = APScheduler()
migrate = Migrate()

# Configure logging for the app
logging.basicConfig(level=logging.INFO)
app_logger = logging.getLogger(__name__)


def register_extensions(app):
    """Registers Flask extensions with the application."""
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # Import User model after db is initialized to avoid circular imports
    # if User model depends on db.Model
    from apps.authentication.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    login_manager.login_view = "authentication_blueprint.login"

    # Only initialize scheduler if not running a migration
    if os.environ.get("FLASK_RUNNING_MIGRATION") != "true":
        scheduler.init_app(app)
    else:
        app_logger.info("Skipping APScheduler initialization during migration.")


def register_blueprints(app):
    """Registers blueprints for different modules."""
    for module_name in ("authentication", "home"):
        module = import_module(f"apps.{module_name}.routes")
        app.register_blueprint(module.blueprint)


def configure_database(app):
    """Configures database session cleanup."""

    @app.teardown_request
    def shutdown_session(exception=None):
        db.session.remove()


def create_app(config):
    """
    Application factory function to create and configure the Flask app.
    Args:
        config: Configuration object (e.g., DebugConfig, ProductionConfig).
    Returns:
        Flask app instance.
    """
    app = Flask(__name__)
    app.config.from_object(config)
    app.logger.setLevel(logging.INFO)

    register_extensions(app)
    register_blueprints(app)
    configure_database(app)

    with app.app_context():
        # db.create_all() is idempotent, so it's safe to call.
        # It will create tables that don't exist and do nothing for existing ones.
        # Removed the 'if not db.engine.dialect.has_table' check for simplicity
        # and to avoid connection issues during app startup in some environments.
        db.create_all()
        app.logger.info("Ensured database tables are created.")

        # Import necessary utilities and models within app context if they depend on the app or db
        from apps.authentication.models import User, RoleType
        from apps.authentication.util import create_superadmin
        from apps.home.utils import initialize_stock_items, get_daily_report_data
        from apps.errors import register_error_handlers

        register_error_handlers(app, db)
        app.logger.info("Error handlers registered.")

        # Initialize stock items (this might also create some initial data)
        initialize_stock_items(app)
        app.logger.info("Stock items initialized.")

        # Only attempt to start/schedule jobs if scheduler was initialized
        # and not running a migration.
        if os.environ.get("FLASK_RUNNING_MIGRATION") != "true":
            if app.config.get("SCHEDULER_API_ENABLED"):
                if not scheduler.running:
                    try:
                        scheduler.start()  # Start the scheduler here
                        app.logger.info("APScheduler started.")
                    except Exception as e:
                        app.logger.error(f"Error starting APScheduler: {e}")
                else:
                    app.logger.info("APScheduler already running.")

                # Schedule daily report generation job
                if not scheduler.get_job("daily_report_gen"):
                    # Only schedule in non-debug or testing environments for production readiness
                    if not app.config.get("DEBUG", False) or app.testing:
                        scheduler.add_job(
                            id="daily_report_gen",
                            func=get_daily_report_data,
                            trigger="cron",
                            hour=0,
                            minute=5,  # 5 minutes past midnight UTC by default, adjust timezone in Config
                            args=[
                                app
                            ],  # Removed 'None' for date, as get_daily_report_data might handle it internally
                            replace_existing=True,
                        )
                        app.logger.info("Daily report generation job scheduled.")
                    else:
                        app.logger.info(
                            "Daily report generation job NOT scheduled in DEBUG mode or when app.testing is False."
                        )
                else:
                    app.logger.info("Daily report generation job already exists.")
            else:
                app.logger.info("Scheduler API not enabled, skipping job scheduling.")
        else:
            app.logger.info("Skipping job scheduling during migration.")

        # Create superadmin if one doesn't exist
        try:
            if not User.query.filter_by(role=RoleType.SUPERADMIN).first():
                if create_superadmin():
                    app.logger.info("Superadmin created successfully.")
                else:
                    app.logger.warning(
                        "Superadmin creation attempted but no superadmin found after."
                    )
            else:
                app.logger.info("Superadmin already exists, skipping creation.")
        except Exception as e:
            app.logger.error(f"Error during superadmin creation: {e}", exc_info=True)
            # Depending on severity, you might want to re-raise or just log
            # raise # Uncomment if app should not start without superadmin

    return app

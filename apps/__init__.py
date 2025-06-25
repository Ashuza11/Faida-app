from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from importlib import import_module
from flask_apscheduler import APScheduler
from flask_migrate import Migrate
import os  # Import os for environment variable check

# Create extensions without importing models
db = SQLAlchemy()
login_manager = LoginManager()
scheduler = APScheduler()
migrate = Migrate()


def register_extensions(app):
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    from apps.authentication.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    login_manager.login_view = "authentication_blueprint.login"

    # CRITICAL CHANGE HERE: Only initialize scheduler if not running a migration
    # Flask-Migrate sets an environment variable when running.
    # This is the most reliable way to prevent scheduler init during migrations.
    if os.environ.get("FLASK_RUNNING_MIGRATION") != "true":
        scheduler.init_app(app)
    else:
        app.logger.info("Skipping APScheduler initialization during migration.")


def register_blueprints(app):
    for module_name in ("authentication", "home"):
        module = import_module(f"apps.{module_name}.routes")
        app.register_blueprint(module.blueprint)


def configure_database(app):
    @app.teardown_request
    def shutdown_session(exception=None):
        db.session.remove()


def create_app(config):
    app = Flask(__name__)
    app.config.from_object(config)
    register_extensions(app)
    register_blueprints(app)
    configure_database(app)

    with app.app_context():
        db.create_all()

        from apps.authentication.models import User, RoleType
        from apps.authentication.util import create_superadmin
        from apps.home.utils import initialize_stock_items, generate_daily_report
        from apps.errors import register_error_handlers

        register_error_handlers(app, db)

        initialize_stock_items(app)

        # Only attempt to start/schedule jobs if scheduler was initialized
        if os.environ.get("FLASK_RUNNING_MIGRATION") != "true":
            if app.config.get("SCHEDULER_API_ENABLED"):
                if not scheduler.running:
                    scheduler.start()  # Start the scheduler here

                if not scheduler.get_job("daily_report_gen"):
                    if not app.config.get("DEBUG", False) or app.testing:
                        scheduler.add_job(
                            id="daily_report_gen",
                            func=generate_daily_report,
                            trigger="cron",
                            hour=0,
                            minute=5,
                            args=[app, None],
                            replace_existing=True,
                        )
                        app.logger.info("Daily report generation job scheduled.")
                    else:
                        app.logger.info(
                            "Daily report generation job NOT scheduled in DEBUG mode."
                        )
                else:
                    app.logger.info("Daily report generation job already exists.")
            else:
                app.logger.info("Scheduler API not enabled, skipping job scheduling.")
        else:
            app.logger.info("Skipping job scheduling during migration.")

        try:
            if not User.query.filter_by(role=RoleType.SUPERADMIN).first():
                if create_superadmin():
                    app.logger.info("Superadmin created successfully")
        except Exception as e:
            app.logger.error(f"Error during superadmin creation: {e}")
            raise

    return app

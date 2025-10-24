import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager


from .config import DebugConfig

# --- Extension Instantiation ---
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "auth_bp.login"
# Optional: Set the message category for flashes
login_manager.login_message_category = "warning"

# ... (rest of your global variables) ...
app_logger = logging.getLogger(__name__)


# --- Application Factory Function ---
def create_app(config_object=DebugConfig):
    app = Flask(__name__)
    app.config.from_object(config_object)

    # ... (logging configuration) ...

    # --- Initialize Extensions (This is where 'db' becomes a real object) ---
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # --- User Loader ---
    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # --- Register Blueprints ---
    with app.app_context():
        from .main import bp as main_bp

        app.register_blueprint(main_bp)

        from .auth import bp as auth_bp

        app.register_blueprint(auth_bp, url_prefix="/auth")

        from .errors import bp as errors_bp

        app.register_blueprint(errors_bp)

        # IMPORTANT: Remove this blueprint registration.
        # The CLI commands are registered directly onto the 'app' object, not as a blueprint.
        # REMOVE THIS LINE: from .cli import cli_bp
        # REMOVE THIS LINE: app.register_blueprint(cli_bp)

        app_logger.info("Blueprints registered.")

    # --- Register CLI Commands (AFTER everything else is initialized) ---
    from apps.cli import register_cli_commands  # Import it here, inside the function

    register_cli_commands(app)  # Call the registration function

    return app

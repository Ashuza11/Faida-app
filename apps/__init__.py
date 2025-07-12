import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

from .config import DebugConfig  # Assuming your config is at /apps/config.py

# --- Extension Instantiation ---
# Extensions are instantiated globally but configured inside the factory.
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

# --- Login Manager Configuration ---
# Point login manager to the login view in your auth blueprint.
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access this page."
app_logger = logging.getLogger(__name__)


# --- Application Factory Function ---
def create_app(config_object=DebugConfig):
    """
    Application factory pattern.
    - Creates and configures the Flask app.
    - Initializes extensions.
    - Registers blueprints.
    """
    app = Flask(__name__)
    app.config.from_object(config_object)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    app.logger.setLevel(logging.INFO)

    # --- Initialize Extensions with the App ---
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # --- User Loader for Flask-Login ---
    # We import the model here to avoid circular imports.
    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # --- Register Blueprints ---
    # Blueprints organize your application into distinct components.
    with app.app_context():
        # Import blueprints here to avoid circular dependencies
        from .main import bp as main_bp

        app.register_blueprint(main_bp)

        from .auth import bp as auth_bp

        app.register_blueprint(auth_bp, url_prefix="/auth")

        from .errors import bp as errors_bp

        app.register_blueprint(errors_bp)

        from .cli import cli_bp

        app.register_blueprint(cli_bp)

        app_logger.info("Blueprints registered.")

    return app

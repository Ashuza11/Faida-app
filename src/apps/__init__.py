from .config import DebugConfig
import logging
import os
from flask import Flask, app, send_file, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager


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
        # If the database is unreachable (e.g. network down), returning None
        # makes Flask-Login treat the request as anonymous instead of crashing.
        # The @login_required decorator then redirects to the login page cleanly.
        try:
            return db.session.get(User, int(user_id))
        except Exception:
            db.session.remove()
            return None

    # --- Register Blueprints ---
    with app.app_context():
        from .main import bp as main_bp
        from apps.health import health_bp

        app.register_blueprint(main_bp)
        app.register_blueprint(health_bp)

        # Register PDF blueprint
        from apps.main.pdf_routes import pdf_bp
        app.register_blueprint(pdf_bp)

        from apps.admin import admin_bp
        app.register_blueprint(admin_bp)

        from .auth import bp as auth_bp

        app.register_blueprint(auth_bp, url_prefix="/auth")

        from .errors import bp as errors_bp

        app.register_blueprint(errors_bp)

        from apps.api import api_bp

        app.register_blueprint(api_bp)

        app_logger.info("Blueprints registered.")

    # ── Service Worker: serve /sw.js at root with full-scope header ──────────
    # The SW file lives at /static/sw.js but must be served from the root
    # path so it can control all app URLs (scope = '/').
    @app.route("/sw.js")
    def service_worker():
        sw_path = os.path.join(app.static_folder, "sw.js")
        response = make_response(send_file(sw_path, mimetype="application/javascript"))
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    # --- Register CLI Commands (AFTER everything else is initialized) ---
    # Import it here, inside the function
    from apps.cli import register_cli_commands

    register_cli_commands(app)

    return app

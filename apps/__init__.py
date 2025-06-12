from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from importlib import import_module

# Create extensions without importing models
db = SQLAlchemy()
login_manager = LoginManager()


def register_extensions(app):
    db.init_app(app)
    login_manager.init_app(app)

    from apps.authentication.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    login_manager.login_view = "auth.login"


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

        # Import models ONLY after db is initialized
        from apps.authentication.models import User, RoleType
        from apps.authentication.util import create_superadmin

        try:
            if not User.query.filter_by(role=RoleType.SUPERADMIN).first():
                if create_superadmin():
                    app.logger.info("Superadmin created successfully")
        except Exception as e:
            app.logger.error(f"Error during superadmin creation: {e}")
            raise  # Re-raise the exception during app creation

    return app

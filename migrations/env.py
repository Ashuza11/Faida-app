import logging
from logging.config import fileConfig
import os  # Import the os module

from alembic import context

from apps import create_app, db
from apps.config import config_dict

# Alembic Config object
config = context.config

# Interpret the config file for Python's standard logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

# --- CRITICAL CHANGE START ---
# Set an environment variable *before* creating the app,
# which your apps/__init__.py can then check.
os.environ["FLASK_RUNNING_MIGRATION"] = "true"
logger.info(
    "FLASK_RUNNING_MIGRATION environment variable set for app context creation."
)
# --- CRITICAL CHANGE END ---

# Setup Flask app context
app_config = config_dict[
    "Debug"
]  # Using "Debug" config, change if needed (e.g., "Production")

# The create_app call will now see FLASK_RUNNING_MIGRATION in its environment
app = create_app(app_config)
app.app_context().push()  # Pushes the application context, allowing access to app.config, etc.

# Target metadata for database migrations
target_metadata = db.metadata

# Set the database URL for Alembic from the Flask app's configuration.
config.set_main_option("sqlalchemy.url", app.config["SQLALCHEMY_DATABASE_URI"])


def run_migrations_offline():
    """
    Run migrations in 'offline' mode.
    This mode does not require a live database connection. Instead,
    it generates SQL statements to be applied manually.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """
    Run migrations in 'online' mode.
    This mode establishes a live database connection and applies migrations directly.
    """
    connectable = db.engine

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

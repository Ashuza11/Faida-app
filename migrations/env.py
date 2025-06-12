import logging
from logging.config import fileConfig

from alembic import context

from apps import create_app, db
from apps.config import config_dict

# Alembic Config object
# This captures the Alembic configuration from alembic.ini
config = context.config

# Interpret the config file for Python's standard logging.
# This ensures that Alembic's logging is properly configured.
fileConfig(config.config_file_name)

# Set up a logger specifically for alembic environment, useful for debugging migration issues.
logger = logging.getLogger("alembic.env")

# Setup Flask app context
# This is crucial for Alembic to access Flask's application configurations,
# especially the database URI.
app_config = config_dict[
    "Debug"
]  # Using "Debug" config, change if needed (e.g., "Production")
app = create_app(app_config)
app.app_context().push()  # Pushes the application context, allowing access to app.config, etc.

# Target metadata for database migrations
# This tells Alembic which database models to track for changes.
target_metadata = db.metadata

# Set the database URL for Alembic from the Flask app's configuration.
# This ensures Alembic connects to the correct database.
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
        literal_binds=True,  # Renders all literal values in the SQL as is
        dialect_opts={"paramstyle": "named"},  # Specify parameter style if needed
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """
    Run migrations in 'online' mode.
    This mode establishes a live database connection and applies migrations directly.
    """
    # Connectable is a SQLAlchemy Engine or Connection object.
    # We get it from the Flask-SQLAlchemy db object.
    connectable = db.engine

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # Enables comparison of column types when auto-generating migrations
        )

        with context.begin_transaction():
            context.run_migrations()


# Determine whether to run migrations in offline or online mode
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

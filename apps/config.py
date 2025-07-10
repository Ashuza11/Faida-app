import os
from decouple import config


class Config(object):
    """Base configuration class with default settings."""

    basedir = os.path.abspath(os.path.dirname(__file__))
    SECRET_KEY = config("SECRET_KEY", default="S#perS3crEt_007")

    # Use DATABASE_URL from environment directly
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL"
    ) or "sqlite:///" + os.path.join(
        basedir, "db.sqlite3"
    )  # Fallback to SQLite if DATABASE_URL is not set

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SCHEDULER_API_ENABLED = True
    SCHEDULER_JOB_DEFAULTS = {
        "coalesce": True,
        "max_instances": 1,
    }
    SCHEDULER_EXECUTORS = {"default": {"type": "threadpool", "max_workers": 20}}
    SCHEDULER_JOBSTORES = {
        "default": {
            "type": "sqlalchemy",
            "url": SQLALCHEMY_DATABASE_URI,
        }
    }
    SCHEDULER_TIMEZONE = "Africa/Lubumbashi"


class ProductionConfig(Config):
    DEBUG = False

    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = 3600

    # No need to redefine SQLALCHEMY_DATABASE_URI if it's set via DATABASE_URL in the base Config
    # If you still want to explicitly define it here and override the base, ensure it's correct.
    # For now, let's assume DATABASE_URL in docker-compose.yml is the source of truth.

    # If you absolutely need to override, you can do:
    # SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") # This would be redundant if base class handles it
    # OR if you prefer the decouple way:
    # SQLALCHEMY_DATABASE_URI = "{}://{}:{}@{}:{}/{}".format(
    #     config("DB_ENGINE", default="postgresql"),
    #     config("DB_USERNAME", default="user"),
    #     config("DB_PASS", default="password"),
    #     config("DB_HOST", default="db_service"),
    #     config("DB_PORT", default=5432),
    #     config("DB_NAME", default="mydatabase"),
    # )


class DebugConfig(Config):
    DEBUG = True

    # No need to redefine SQLALCHEMY_DATABASE_URI if it's set via DATABASE_URL in the base Config
    # If you absolutely need to override, you can do:
    # SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    # OR if you prefer the decouple way:
    # SQLALCHEMY_DATABASE_URI = "{}://{}:{}@{}:{}/{}".format(
    #     config("DB_ENGINE", default="postgresql"),
    #     config("DB_USERNAME", default="user"),
    #     config("DB_PASS", default="password"),
    #     config("DB_HOST", default="db_service"),
    #     config("DB_PORT", default=5432),
    #     config("DB_NAME", default="mydatabase"),
    # )


# The rest of your config remains the same.
config_dict = {"Production": ProductionConfig, "Debug": DebugConfig}

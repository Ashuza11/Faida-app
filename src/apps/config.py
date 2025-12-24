import os
from decouple import config

class Config(object):
    # Base directory for relative paths (e.g., SQLite DB)
    basedir = os.path.abspath(os.path.dirname(__file__))
    
    # SECRET_KEY is accessed via os.environ, falling back to a default via decouple
    SECRET_KEY = os.environ.get("SECRET_KEY", config("SECRET_KEY", default="S#perS3crEt_007"))

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SALES_PER_PAGE = 5
    PURCHASES_PER_PAGE = 5
    
    # Base configuration for database connection parameters, retrieved from OS environment
    DBUSER = os.environ.get("DBUSER")
    DBPASS = os.environ.get("DBPASS")
    DBHOST = os.environ.get("DBHOST")
    DBNAME = os.environ.get("DBNAME")


class ProductionConfig(Config):
    """Configuration for Azure deployment (Production, Postgres with SSL)"""
    DEBUG = False

    # Azure production ALWAYS uses PostgreSQL with SSL required
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql+psycopg2://{Config.DBUSER}:{Config.DBPASS}"
        f"@{Config.DBHOST}/{Config.DBNAME}?sslmode=require"
    )

    ALLOWED_HOSTS = [".azurecontainerapps.io"]
    CSRF_TRUSTED_ORIGINS = ["https://*.azurecontainerapps.io"]


class DevelopmentConfig(Config):
    """Configuration for running with Docker Compose (Local Development, Postgres without SSL)"""
    DEBUG = True
    
    # Use environment variables for connection (provided by docker-compose)
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql+psycopg2://{Config.DBUSER}:{Config.DBPASS}"
        f"@{Config.DBHOST}/{Config.DBNAME}" # Note: SSL is NOT required for local Docker
    )

    ALLOWED_HOSTS = []
    CSRF_TRUSTED_ORIGINS = []


class DebugConfig(Config):
    """Configuration for simple local debugging (Fallback to SQLite)"""
    DEBUG = True

    # Debug ALWAYS uses SQLite for simplicity
    SQLALCHEMY_DATABASE_URI = (
        "sqlite:///" + os.path.join(Config.basedir, "db.sqlite3")
    )

    ALLOWED_HOSTS = []
    CSRF_TRUSTED_ORIGINS = []


config_dict = {
    "Production": ProductionConfig,
    "Development": DevelopmentConfig,
    "Debug": DebugConfig
}
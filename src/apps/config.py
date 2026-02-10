"""
Flask Application Configuration

Supports multiple environments:
- Production (Neon PostgreSQL on Render)
- Development (Neon dev branch or local PostgreSQL)
- Debug (SQLite for quick local testing)

Environment is determined by FLASK_ENV environment variable.
"""

import os
from datetime import timedelta


class Config:
    """Base configuration with sensible defaults."""

    # ===========================================
    # Paths
    # ===========================================
    basedir = os.path.abspath(os.path.dirname(__file__))

    # ===========================================
    # Security
    # ===========================================
    SECRET_KEY = os.environ.get(
        'SECRET_KEY', 'dev-secret-key-change-in-production')

    # Session settings
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_SECURE = False  # Override in production
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # CSRF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour

    # ===========================================
    # Database
    # ===========================================
    # Primary: Use DATABASE_URL if available (Render, Heroku, Neon standard)
    DATABASE_URL = os.environ.get('DATABASE_URL')

    # Fallback: Build from individual components (legacy Azure support)
    DBUSER = os.environ.get('DBUSER')
    DBPASS = os.environ.get('DBPASS')
    DBHOST = os.environ.get('DBHOST')
    DBNAME = os.environ.get('DBNAME')

    @staticmethod
    def _fix_postgres_url(url: str | None):
        """
        Fix PostgreSQL URL format issues.
        - Heroku/Render sometimes use 'postgres://' which SQLAlchemy 1.4+ doesn't accept
        - Ensures proper driver is specified
        """
        if not url:
            return None

        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)

        if url.startswith("postgresql://") and "+psycopg2" not in url:
            url = url.replace(
                "postgresql://",
                "postgresql+psycopg2://",
                1,
            )

        return url

    @classmethod
    def get_database_uri(cls, require_ssl=False):
        """
        Build database URI from available configuration.
        Priority: DATABASE_URL > Individual components > SQLite fallback
        """
        # Option 1: DATABASE_URL (preferred for Neon/Render)
        if cls.DATABASE_URL:
            url = cls._fix_postgres_url(cls.DATABASE_URL)
            # Add SSL if required and not already present
            if require_ssl and '?' not in url:
                url += '?sslmode=require'
            elif require_ssl and 'sslmode' not in url:
                url += '&sslmode=require'
            return url

        # Option 2: Individual components (legacy)
        if all([cls.DBUSER, cls.DBPASS, cls.DBHOST, cls.DBNAME]):
            ssl_param = '?sslmode=require' if require_ssl else ''
            return (
                f"postgresql+psycopg2://{cls.DBUSER}:{cls.DBPASS}"
                f"@{cls.DBHOST}/{cls.DBNAME}{ssl_param}"
            )

        # Option 3: SQLite fallback
        return 'sqlite:///' + os.path.join(cls.basedir, 'db.sqlite3')

    SQLALCHEMY_DATABASE_URI = None  # Set in subclasses
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Connection pool settings (optimized for Neon serverless)
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': 5,
        'max_overflow': 10,
        'pool_timeout': 30,
    }

    # ===========================================
    # Application Settings
    # ===========================================
    SALES_PER_PAGE = 10
    PURCHASES_PER_PAGE = 10
    CLIENTS_PER_PAGE = 20

    # File uploads
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

    # ===========================================
    # Phone Number Validation (DRC)
    # ===========================================
    SUPPORTED_COUNTRY_CODES = ['+243', '243', '0']
    DRC_MOBILE_PREFIXES = [
        '81', '82', '83', '84', '85',  # Vodacom
        '89', '99',                     # Airtel
        '90', '91', '97', '98',        # Orange
        '80', '86', '87', '88',        # Africell
    ]


class ProductionConfig(Config):
    """
    Production configuration for Render with Neon PostgreSQL.
    """
    DEBUG = False
    TESTING = False

    # SECRET_KEY - Required in production (set in Render environment variables)
    SECRET_KEY = os.environ.get('SECRET_KEY')

    # Database with SSL required
    SQLALCHEMY_DATABASE_URI = Config.get_database_uri(require_ssl=True)

    # Stricter connection pool for production
    SQLALCHEMY_ENGINE_OPTIONS = {
        **Config.SQLALCHEMY_ENGINE_OPTIONS,
        'pool_size': 10,
        'max_overflow': 20,
        'pool_timeout': 60,
        'connect_args': {
            'sslmode': 'require',
            'connect_timeout': 10,
        }
    }

    # Security
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True

    # Render-specific
    PREFERRED_URL_SCHEME = 'https'


class DevelopmentConfig(Config):
    """
    Development configuration.
    Uses Neon dev branch or local PostgreSQL via Docker.
    """
    DEBUG = True
    TESTING = False

    # Database - SSL optional for development
    SQLALCHEMY_DATABASE_URI = Config.get_database_uri(require_ssl=False)

    # Relaxed security for development
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = True

    # More verbose for debugging
    SQLALCHEMY_ECHO = False  # Set True to see SQL queries


class DebugConfig(Config):
    """
    Simple local debugging with SQLite.
    No external dependencies required.
    """
    DEBUG = True
    TESTING = False

    # Always use SQLite for debug mode
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + \
        os.path.join(Config.basedir, 'db.sqlite3')

    # Minimal connection settings for SQLite
    SQLALCHEMY_ENGINE_OPTIONS = {}

    # Relaxed security
    SESSION_COOKIE_SECURE = False


class TestingConfig(Config):
    """
    Testing configuration with in-memory SQLite.
    """
    DEBUG = True
    TESTING = True

    # In-memory database for fast tests
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'TEST_DATABASE_URL', 'sqlite:///:memory:')

    # Disable CSRF for testing
    WTF_CSRF_ENABLED = False

    # Minimal settings
    SQLALCHEMY_ENGINE_OPTIONS = {}


# Configuration dictionary
config_dict = {
    'production': ProductionConfig,
    'development': DevelopmentConfig,
    'debug': DebugConfig,
    'testing': TestingConfig,
    # Legacy keys (for backward compatibility)
    'Production': ProductionConfig,
    'Development': DevelopmentConfig,
    'Debug': DebugConfig,
}


def get_config():
    """
    Get configuration based on FLASK_ENV environment variable.

    Priority:
    1. FLASK_ENV environment variable
    2. Default to 'development'
    """
    env = os.environ.get('FLASK_ENV', 'development').lower()
    return config_dict.get(env, DevelopmentConfig)

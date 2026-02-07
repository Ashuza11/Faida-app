# run.py
"""
Flask Application Entry Point

Environment detection is based on FLASK_ENV:
- production: Neon PostgreSQL on Render
- development: Neon dev branch or local PostgreSQL
- debug: Local SQLite (no external dependencies)
- testing: In-memory SQLite

Usage:
    # Development with Flask dev server
    flask run
    
    # Production with Gunicorn
    gunicorn -c gunicorn-cfg.py run:app
"""

import os
import logging
from flask_migrate import Migrate
from apps import create_app, db
from apps.config import config_dict

# ===========================================
# Environment Detection
# ===========================================


def get_environment():
    """
    Determine the application environment.

    Priority:
    1. FLASK_ENV environment variable (explicit)
    2. RUNNING_IN_PRODUCTION flag (Render/Azure)
    3. DATABASE_URL presence (cloud deployment)
    4. Default to 'debug' (safest for local)
    """
    # Explicit environment setting (preferred)
    flask_env = os.environ.get('FLASK_ENV', '').lower()

    if flask_env in ['production', 'development', 'testing', 'debug']:
        return flask_env

    # Legacy: Check for production flag
    if os.environ.get('RUNNING_IN_PRODUCTION'):
        return 'production'

    # Infer from DATABASE_URL
    if os.environ.get('DATABASE_URL'):
        # Has external DB, likely development with Neon
        return 'development'

    # Default: Local SQLite debug mode
    return 'debug'


# ===========================================
# Application Setup
# ===========================================

# Determine environment
ENVIRONMENT = get_environment()
DEBUG = ENVIRONMENT in ['development', 'debug', 'testing']

# Get configuration class
config_mode = ENVIRONMENT.capitalize() if ENVIRONMENT != 'debug' else 'Debug'
app_config = config_dict.get(config_mode, config_dict['Debug'])

# Create Flask application
app = create_app(app_config)

# Initialize Flask-Migrate
migrate = Migrate(app, db)

# ===========================================
# Logging Setup
# ===========================================

# Configure logging level
log_level = logging.DEBUG if DEBUG else logging.INFO
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Log startup information
with app.app_context():
    app.logger.info(f"🚀 Starting Faida App in {ENVIRONMENT.upper()} mode")
    app.logger.info(f"   Debug: {DEBUG}")

    # Log database type (without exposing credentials)
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'sqlite' in db_uri:
        app.logger.info("   Database: SQLite (local)")
    elif 'neon.tech' in db_uri:
        app.logger.info("   Database: Neon PostgreSQL (cloud)")
    elif 'postgresql' in db_uri:
        app.logger.info("   Database: PostgreSQL")
    else:
        app.logger.info("   Database: Unknown")


# ===========================================
# CLI Commands Registration
# ===========================================

@app.cli.command('check-db')
def check_db():
    """Check database connection."""
    from sqlalchemy import text
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✅ Database connection successful!")

            # Show PostgreSQL version if applicable
            if 'postgresql' in str(db.engine.url):
                version = conn.execute(text("SELECT version()")).scalar()
                print(f"   PostgreSQL: {version[:50]}...")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return 1


# ===========================================
# Development Server
# ===========================================

if __name__ == "__main__":
    # Get port from environment or default to 5000
    port = int(os.environ.get('PORT', 5000))

    # Run development server
    app.run(
        host='0.0.0.0',
        port=port,
        debug=DEBUG
    )

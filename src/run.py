from flask_migrate import Migrate
from sys import exit
from decouple import config 
from apps import create_app, db
from apps.config import config_dict
import os

# --- ENVIRONMENT DETECTION LOGIC ---

# 1. Production Mode Check (Highest Priority)
IS_PRODUCTION = "RUNNING_IN_PRODUCTION" in os.environ

if IS_PRODUCTION:
    get_config_mode = "Production"
    DEBUG = False
    
# 2. Local Docker Compose Check
elif os.environ.get("FLASK_ENV") == "development" and "DBHOST" in os.environ: 
    get_config_mode = "Development"
    DEBUG = True
    
# 3. Default Local Debug (Fallback to SQLite)
else:
    get_config_mode = "Debug"
    DEBUG = True

# Set the environment string used for logging
ENVIRONMENT = get_config_mode.lower()


# --- APP INITIALIZATION ---

app_config = config_dict[get_config_mode]

# Create Flask app using the determined configuration
app = create_app(app_config)
app.app_context().push()
Migrate(app, db) # Initialize Flask-Migrate

# Log environment info
app.logger.info(f"Environment: {ENVIRONMENT}")
app.logger.info(f"DEBUG: {DEBUG}")
app.logger.info(f"DB URI: {app_config.SQLALCHEMY_DATABASE_URI}")

if __name__ == "__main__":
    # Use the determined DEBUG flag
    app.run(host="0.0.0.0", port=config("PORT", default=5000, cast=int), debug=DEBUG)
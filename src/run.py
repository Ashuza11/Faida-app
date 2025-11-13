from flask_migrate import Migrate
from sys import exit
from decouple import config
from apps import create_app, db
from apps.config import config_dict
from apps.settings.production import Config as ProdConfig

# Detect if running in Azure or locally
ENVIRONMENT = config("ENVIRONMENT", default="development").lower()
DEBUG = ENVIRONMENT != "production"

if DEBUG:
    get_config_mode = "Debug"
    app_config = config_dict[get_config_mode]
else:
    app_config = ProdConfig  # Directly use your production settings

# Create Flask app
app = create_app(app_config)
app.app_context().push()
Migrate(app, db)

# Log environment info
app.logger.info(f"Environment: {ENVIRONMENT}")
app.logger.info(f"DEBUG: {DEBUG}")
app.logger.info(f"DB URI: {app_config.SQLALCHEMY_DATABASE_URI}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config("PORT", default=5000, cast=int), debug=DEBUG)

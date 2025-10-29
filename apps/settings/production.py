from decouple import config
from apps.config import ProductionConfig


class Config(ProductionConfig):
    # Azure Container Apps injects env vars via KeyVault & Bicep
    SQLALCHEMY_DATABASE_URI = f"postgresql://{config('DBUSER')}:{config('DBPASS')}@{config('DBHOST')}/{config('DBNAME')}"
    SECRET_KEY = config("FLASKSECRET", default="change-this")
    DEBUG = False

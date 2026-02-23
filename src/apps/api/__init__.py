from flask import Blueprint

api_bp = Blueprint("api_bp", __name__, url_prefix="/api/v1")

from apps.api import routes  # noqa: F401, E402

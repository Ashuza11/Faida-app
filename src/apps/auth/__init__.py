from flask import Blueprint

bp = Blueprint("auth_bp", __name__, url_prefix="/auth")

from apps.auth import routes

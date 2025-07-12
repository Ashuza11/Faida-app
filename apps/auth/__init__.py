from flask import Blueprint

bp = Blueprint("authentication_blueprint", __name__, url_prefix="")

from apps.auth import routes

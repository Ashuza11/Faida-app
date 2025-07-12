from flask import Blueprint

bp = Blueprint("main_blueprint", __name__, url_prefix="")

from apps.main import routes

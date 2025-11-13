from flask import Blueprint

bp = Blueprint("main_bp", __name__, url_prefix="")

from apps.main import routes

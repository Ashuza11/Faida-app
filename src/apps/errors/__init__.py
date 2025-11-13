from flask import Blueprint

bp = Blueprint("errors", __name__)

from apps.errors import handlers

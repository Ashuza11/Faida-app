from flask import app, render_template
from apps.errors import bp
from apps import db


@bp.app_errorhandler(403)
def forbidden_error(error):
    # Error handler for 403 Forbidden
    return render_template("errors/403.html"), 403


@bp.app_errorhandler(404)
# Error handler for 404 Not Found
def not_found_error(error):
    return render_template("errors/404.html"), 404


@bp.app_errorhandler(500)
# Error handler for 500 Internal Server Error
def internal_error(error):
    db.session.rollback()  # Crucial for database errors
    return render_template("errors/500.html"), 500


@bp.app_errorhandler(401)
def unauthorized_error(error):
    return render_template("errors/401.html"), 401

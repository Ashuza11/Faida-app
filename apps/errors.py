from flask import render_template
from flask_login import (
    current_user,
)


def register_error_handlers(app, db):
    # Error handler for 403 Forbidden
    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template("errors/403.html"), 403

    # Error handler for 404 Not Found
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template("errors/404.html"), 404

    # Error handler for 500 Internal Server Error
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()  # Crucial for database errors
        return render_template("errors/500.html"), 500

    # @app.errorhandler(401)
    # def unauthorized_error(error):
    #     return render_template('errors/401.html'), 401

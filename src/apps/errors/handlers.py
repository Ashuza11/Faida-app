import logging
from flask import render_template
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from apps.errors import bp
from apps import db

logger = logging.getLogger(__name__)


def _safe_rollback():
    """Rollback the DB session without raising if the connection is dead."""
    try:
        db.session.rollback()
    except Exception:
        pass
    finally:
        try:
            db.session.remove()
        except Exception:
            pass


# ── HTTP error handlers ───────────────────────────────────────────────────────

@bp.app_errorhandler(400)
def bad_request_error(error):
    return render_template("errors/400.html"), 400


@bp.app_errorhandler(401)
def unauthorized_error(error):
    return render_template("errors/401.html"), 401


@bp.app_errorhandler(403)
def forbidden_error(error):
    return render_template("errors/403.html"), 403


@bp.app_errorhandler(404)
def not_found_error(error):
    return render_template("errors/404.html"), 404


@bp.app_errorhandler(500)
def internal_error(error):
    _safe_rollback()
    logger.error("500 Internal Server Error: %s", error)
    return render_template("errors/500.html"), 500


@bp.app_errorhandler(503)
def service_unavailable_error(error):
    _safe_rollback()
    return render_template("errors/503.html"), 503


# ── Database / connectivity exception handlers ────────────────────────────────
# These catch SQLAlchemy exceptions that bubble up through view functions
# BEFORE Flask converts them to a 500 response — letting us show a friendlier
# "base de données indisponible" page instead of a generic server error.

@bp.app_errorhandler(OperationalError)
def db_operational_error(error):
    """Handles DB connection failures (network down, Neon unreachable, etc.)."""
    _safe_rollback()
    logger.error("Database OperationalError: %s", error)
    return render_template("errors/503.html"), 503


@bp.app_errorhandler(SQLAlchemyError)
def db_generic_error(error):
    """Handles any other SQLAlchemy error not caught by OperationalError handler."""
    _safe_rollback()
    logger.error("SQLAlchemyError: %s", error)
    return render_template("errors/500.html"), 500

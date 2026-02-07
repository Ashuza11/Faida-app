"""
Health check endpoints for monitoring and load balancer integration.
"""

from flask import Blueprint, jsonify, current_app
from apps import db
from sqlalchemy import text

health_bp = Blueprint('health', __name__)


@health_bp.route('/health')
def health_check():
    """
    Basic health check endpoint.
    Returns 200 if the application is running.
    Used by Render for health checks.
    """
    return jsonify({
        'status': 'healthy',
        'service': 'airtfast'
    }), 200


@health_bp.route('/health/ready')
def readiness_check():
    """
    Readiness check - verifies database connectivity.
    Returns 200 only if all dependencies are available.
    """
    checks = {
        'database': False,
        'status': 'unhealthy'
    }

    # Check database connection
    try:
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks['database'] = True
    except Exception as e:
        checks['database_error'] = str(e)
        return jsonify(checks), 503

    checks['status'] = 'ready'
    return jsonify(checks), 200


@health_bp.route('/health/live')
def liveness_check():
    """
    Liveness check - verifies the application process is alive.
    Simpler than readiness, doesn't check external dependencies.
    """
    return jsonify({
        'status': 'alive',
        'debug': current_app.debug
    }), 200

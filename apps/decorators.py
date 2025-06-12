from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user
from apps.authentication.models import RoleType


def roles_required(*roles):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("authentication_blueprint.login"))
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)

        return decorated_function

    return wrapper


def superadmin_required(f):
    return roles_required(RoleType.SUPERADMIN)(f)


def vendeur_required(f):
    return roles_required(RoleType.SUPERADMIN, RoleType.VENDEUR)(f)

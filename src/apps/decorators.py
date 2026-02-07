"""
Route Decorators for Access Control - Multi-Tenant

Updated decorators with data isolation support.
"""

from functools import wraps
from flask import flash, redirect, url_for, abort
from flask_login import current_user, login_required


def platform_admin_required(f):
    """
    Restrict access to platform administrators only.
    Use for: Platform settings, viewing all businesses, creating invite codes.
    """
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_platform_admin:
            flash("Accès réservé aux administrateurs de la plateforme.", "danger")
            return redirect(url_for("main_bp.index"))
        return f(*args, **kwargs)
    return decorated_function


def vendeur_required(f):
    """
    Restrict access to vendeurs (business owners) and platform admins.
    Use for: Business settings, stock purchases, reports, managing stockeurs.

    Note: Platform admins can access for support purposes.
    """
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not (current_user.is_vendeur or current_user.is_platform_admin):
            flash("Accès réservé aux propriétaires d'entreprise.", "warning")
            return redirect(url_for("main_bp.index"))
        return f(*args, **kwargs)
    return decorated_function


def business_member_required(f):
    """
    Restrict access to anyone who is part of a business.
    Includes: Vendeurs, Stockeurs, and Platform Admins.

    Use for: Recording sales, viewing clients, basic operations.
    """
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        # Platform admins can access everything
        if current_user.is_platform_admin:
            return f(*args, **kwargs)

        # Vendeurs are business members
        if current_user.is_vendeur:
            return f(*args, **kwargs)

        # Stockeurs must belong to a vendeur
        if current_user.is_stockeur:
            if current_user.vendeur_id is None:
                flash("Votre compte n'est pas associé à une entreprise.", "danger")
                return redirect(url_for("main_bp.index"))
            return f(*args, **kwargs)

        flash("Accès non autorisé.", "danger")
        return redirect(url_for("auth_bp.login"))

    return decorated_function

# ===========================================
# Data Access Helpers (use in routes)
# ===========================================


def get_current_vendeur_id():
    """
    Get the vendeur_id for data scoping based on current user.

    Returns:
        - None if platform admin (can see all)
        - User's vendeur_id if vendeur (their own id)
        - Employer's id if stockeur

    Use in routes like:
        vendeur_id = get_current_vendeur_id()
        if vendeur_id:
            stocks = Stock.query.filter_by(vendeur_id=vendeur_id).all()
        else:
            stocks = Stock.query.all()  # Admin sees all
    """
    if not current_user.is_authenticated:
        return None

    return current_user.business_vendeur_id


def filter_by_vendeur(query, model_class):
    """
    Apply vendeur filter to a query.

    For platform admins: Returns unfiltered query
    For others: Returns query filtered by their vendeur_id

    Args:
        query: SQLAlchemy query object
        model_class: Model class that has vendeur_id column

    Example:
        base_query = Sale.query
        filtered_query = filter_by_vendeur(base_query, Sale)
        sales = filtered_query.order_by(Sale.created_at.desc()).all()
    """
    vendeur_id = get_current_vendeur_id()

    if vendeur_id is not None:
        return query.filter(model_class.vendeur_id == vendeur_id)

    # Platform admin sees all
    return query


def can_access_resource(resource) -> bool:
    """
    Check if current user can access a specific resource.

    Args:
        resource: Any object with vendeur_id attribute

    Returns:
        True if user can access, False otherwise
    """
    if not hasattr(resource, 'vendeur_id'):
        return False

    if current_user.is_platform_admin:
        return True

    return current_user.can_access_vendeur_data(resource.vendeur_id)


def ensure_access(resource):
    """
    Ensure current user can access resource, abort 403 if not.

    Usage in route:
        sale = Sale.query.get_or_404(sale_id)
        ensure_access(sale)  # Aborts if user can't access
    """
    if not can_access_resource(resource):
        abort(403)

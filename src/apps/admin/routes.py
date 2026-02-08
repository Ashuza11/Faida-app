# ============================================================
# PLATFORM ADMIN ROUTES - apps/admin/routes.py
# ============================================================
# FIXED to match actual InviteCode model structure
# ============================================================

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import secrets

from apps import db
from apps.models import (
    User, RoleType, InviteCode, Sale, Stock,
    StockPurchase, Client, DailyOverallReport
)
from apps.decorators import platform_admin_required

bp = Blueprint('admin_bp', __name__, url_prefix='/admin')


# ============================================================
# ADMIN DASHBOARD - Overview
# ============================================================

@bp.route('/')
@bp.route('/dashboard')
@login_required
@platform_admin_required
def dashboard():
    """Platform admin main dashboard with overview stats."""

    # Count stats
    total_vendeurs = User.query.filter_by(role=RoleType.VENDEUR).count()
    total_stockeurs = User.query.filter_by(role=RoleType.STOCKEUR).count()

    # InviteCode: used_by_id is None = not used yet
    active_invite_codes = InviteCode.query.filter_by(
        used_by_id=None, is_active=True).count()
    used_invite_codes = InviteCode.query.filter(
        InviteCode.used_by_id.isnot(None)).count()

    # Recent vendeurs (last 7 days)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    new_vendeurs_week = User.query.filter(
        User.role == RoleType.VENDEUR,
        User.created_at >= week_ago
    ).count()

    # Total sales across platform (today)
    today = datetime.now(timezone.utc).date()
    today_start = datetime.combine(
        today, datetime.min.time()).replace(tzinfo=timezone.utc)
    today_end = datetime.combine(
        today, datetime.max.time()).replace(tzinfo=timezone.utc)

    total_sales_today = db.session.query(
        db.func.sum(Sale.total_amount_due)
    ).filter(
        Sale.created_at >= today_start,
        Sale.created_at <= today_end
    ).scalar() or Decimal('0.00')

    total_cash_today = db.session.query(
        db.func.sum(Sale.cash_paid)
    ).filter(
        Sale.created_at >= today_start,
        Sale.created_at <= today_end
    ).scalar() or Decimal('0.00')

    # Recent vendeurs list
    recent_vendeurs = User.query.filter_by(
        role=RoleType.VENDEUR
    ).order_by(User.created_at.desc()).limit(5).all()

    # Recent invite codes
    recent_codes = InviteCode.query.order_by(
        InviteCode.created_at.desc()
    ).limit(5).all()

    return render_template(
        'admin/dashboard.html',
        total_vendeurs=total_vendeurs,
        total_stockeurs=total_stockeurs,
        active_invite_codes=active_invite_codes,
        used_invite_codes=used_invite_codes,
        new_vendeurs_week=new_vendeurs_week,
        total_sales_today=total_sales_today,
        total_cash_today=total_cash_today,
        recent_vendeurs=recent_vendeurs,
        recent_codes=recent_codes,
        segment='admin',
        sub_segment='dashboard'
    )


# ============================================================
# VENDEURS MANAGEMENT
# ============================================================

@bp.route('/vendeurs')
@login_required
@platform_admin_required
def vendeurs_list():
    """List all vendeurs on the platform."""

    page = request.args.get('page', 1, type=int)
    per_page = 10

    # Search functionality
    search = request.args.get('search', '').strip()

    query = User.query.filter_by(role=RoleType.VENDEUR)

    if search:
        query = query.filter(
            db.or_(
                User.username.ilike(f'%{search}%'),
                User.phone.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%')
            )
        )

    vendeurs = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Get stats for each vendeur
    vendeur_stats = {}
    for vendeur in vendeurs.items:
        # Count stockeurs
        stockeur_count = User.query.filter_by(vendeur_id=vendeur.id).count()

        # Count clients
        client_count = Client.query.filter_by(vendeur_id=vendeur.id).count()

        # Total sales
        total_sales = db.session.query(
            db.func.sum(Sale.total_amount_due)
        ).filter(Sale.vendeur_id == vendeur.id).scalar() or Decimal('0.00')

        vendeur_stats[vendeur.id] = {
            'stockeurs': stockeur_count,
            'clients': client_count,
            'total_sales': total_sales
        }

    return render_template(
        'admin/vendeurs.html',
        vendeurs=vendeurs,
        vendeur_stats=vendeur_stats,
        search=search,
        segment='admin',
        sub_segment='vendeurs'
    )


@bp.route('/vendeurs/<int:vendeur_id>')
@login_required
@platform_admin_required
def vendeur_detail(vendeur_id):
    """View detailed info about a specific vendeur."""

    vendeur = User.query.get_or_404(vendeur_id)

    if vendeur.role != RoleType.VENDEUR:
        flash("Cet utilisateur n'est pas un vendeur.", "warning")
        return redirect(url_for('admin_bp.vendeurs_list'))

    # Get stockeurs
    stockeurs = User.query.filter_by(vendeur_id=vendeur.id).all()

    # Get clients
    clients = Client.query.filter_by(vendeur_id=vendeur.id).limit(10).all()

    # Get recent sales
    recent_sales = Sale.query.filter_by(
        vendeur_id=vendeur.id
    ).order_by(Sale.created_at.desc()).limit(10).all()

    # Get stocks
    stocks = Stock.query.filter_by(vendeur_id=vendeur.id).all()

    # Stats
    total_sales = db.session.query(
        db.func.sum(Sale.total_amount_due)
    ).filter(Sale.vendeur_id == vendeur.id).scalar() or Decimal('0.00')

    total_debt = db.session.query(
        db.func.sum(Sale.debt_amount)
    ).filter(
        Sale.vendeur_id == vendeur.id,
        Sale.debt_amount > 0
    ).scalar() or Decimal('0.00')

    total_stock_value = sum(
        (s.balance or 0) * (s.selling_price_per_unit or 0)
        for s in stocks
    )

    return render_template(
        'admin/vendeur_detail.html',
        vendeur=vendeur,
        stockeurs=stockeurs,
        clients=clients,
        recent_sales=recent_sales,
        stocks=stocks,
        total_sales=total_sales,
        total_debt=total_debt,
        total_stock_value=total_stock_value,
        segment='admin',
        sub_segment='vendeurs'
    )


@bp.route('/vendeurs/<int:vendeur_id>/toggle-status', methods=['POST'])
@login_required
@platform_admin_required
def toggle_vendeur_status(vendeur_id):
    """Activate or deactivate a vendeur."""

    vendeur = User.query.get_or_404(vendeur_id)

    if vendeur.role != RoleType.VENDEUR:
        flash("Action non autorisée.", "danger")
        return redirect(url_for('admin_bp.vendeurs_list'))

    vendeur.is_active = not vendeur.is_active
    db.session.commit()

    status = "activé" if vendeur.is_active else "désactivé"
    flash(f"Le vendeur {vendeur.username} a été {status}.", "success")

    return redirect(url_for('admin_bp.vendeur_detail', vendeur_id=vendeur_id))


# ============================================================
# INVITE CODES MANAGEMENT
# ============================================================

@bp.route('/invite-codes')
@login_required
@platform_admin_required
def invite_codes_list():
    """List all invite codes."""

    page = request.args.get('page', 1, type=int)
    per_page = 15

    # Filter by status
    status_filter = request.args.get('status', 'all')

    query = InviteCode.query

    if status_filter == 'active':
        # Active = not used and is_active
        query = query.filter_by(used_by_id=None, is_active=True)
    elif status_filter == 'used':
        # Used = used_by_id is not None
        query = query.filter(InviteCode.used_by_id.isnot(None))

    codes = query.order_by(InviteCode.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Stats
    total_codes = InviteCode.query.count()
    active_codes = InviteCode.query.filter_by(
        used_by_id=None, is_active=True).count()
    used_codes = InviteCode.query.filter(
        InviteCode.used_by_id.isnot(None)).count()

    return render_template(
        'admin/invite_codes.html',
        codes=codes,
        status_filter=status_filter,
        total_codes=total_codes,
        active_codes=active_codes,
        used_codes=used_codes,
        segment='admin',
        sub_segment='invite_codes'
    )


@bp.route('/invite-codes/create', methods=['POST'])
@login_required
@platform_admin_required
def create_invite_code():
    """Generate a new invite code."""

    # Generate unique code
    code = secrets.token_urlsafe(8).upper()[:10]

    # Make sure it's unique
    while InviteCode.query.filter_by(code=code).first():
        code = secrets.token_urlsafe(8).upper()[:10]

    new_code = InviteCode(
        code=code,
        created_by_id=current_user.id,  # Fixed: was created_by
        is_active=True
    )

    db.session.add(new_code)
    db.session.commit()

    flash(f"Code d'invitation créé: {code}", "success")

    return redirect(url_for('admin_bp.invite_codes_list'))


@bp.route('/invite-codes/<int:code_id>/delete', methods=['POST'])
@login_required
@platform_admin_required
def delete_invite_code(code_id):
    """Delete an unused invite code."""

    code = InviteCode.query.get_or_404(code_id)

    # Check if used (used_by_id is not None)
    if code.used_by_id is not None:
        flash("Impossible de supprimer un code déjà utilisé.", "warning")
        return redirect(url_for('admin_bp.invite_codes_list'))

    db.session.delete(code)
    db.session.commit()

    flash("Code d'invitation supprimé.", "success")

    return redirect(url_for('admin_bp.invite_codes_list'))


@bp.route('/invite-codes/<int:code_id>/toggle', methods=['POST'])
@login_required
@platform_admin_required
def toggle_invite_code(code_id):
    """Activate or deactivate an invite code."""

    code = InviteCode.query.get_or_404(code_id)

    # Can't toggle if already used
    if code.used_by_id is not None:
        flash("Impossible de modifier un code déjà utilisé.", "warning")
        return redirect(url_for('admin_bp.invite_codes_list'))

    code.is_active = not code.is_active
    db.session.commit()

    status = "activé" if code.is_active else "désactivé"
    flash(f"Code {code.code} {status}.", "success")

    return redirect(url_for('admin_bp.invite_codes_list'))


# ============================================================
# PLATFORM STATS & REPORTS
# ============================================================

@bp.route('/stats')
@login_required
@platform_admin_required
def platform_stats():
    """View platform-wide statistics."""

    # Date range
    days = request.args.get('days', 30, type=int)
    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    # Daily sales for chart
    daily_sales = db.session.query(
        db.func.date(Sale.created_at).label('date'),
        db.func.sum(Sale.total_amount_due).label('total'),
        db.func.sum(Sale.cash_paid).label('cash'),
        db.func.count(Sale.id).label('count')
    ).filter(
        Sale.created_at >= start_date
    ).group_by(
        db.func.date(Sale.created_at)
    ).order_by(
        db.func.date(Sale.created_at)
    ).all()

    # Top vendeurs by sales
    top_vendeurs = db.session.query(
        User.username,
        db.func.sum(Sale.total_amount_due).label('total_sales'),
        db.func.count(Sale.id).label('sale_count')
    ).join(
        Sale, Sale.vendeur_id == User.id
    ).filter(
        Sale.created_at >= start_date
    ).group_by(
        User.id, User.username
    ).order_by(
        db.func.sum(Sale.total_amount_due).desc()
    ).limit(10).all()

    return render_template(
        'admin/stats.html',
        daily_sales=daily_sales,
        top_vendeurs=top_vendeurs,
        days=days,
        segment='admin',
        sub_segment='stats'
    )

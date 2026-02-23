"""
Authentication Routes - Phone-based login with invite code registration

Flows:
1. Login: Phone + Password
2. Vendeur Registration: Invite Code + Phone + Password (creates stock automatically)
3. Logout: Standard Flask-Login
"""

from flask import render_template, redirect, request, url_for, flash, current_app
from flask_login import current_user, login_user, logout_user, login_required
from datetime import datetime, timezone
from urllib.parse import urlparse


from apps.auth import bp
from apps.auth.forms import LoginForm, VendeurRegistrationForm, CreateAccountForm
from apps.models import (
    User,
    RoleType,
    InviteCode,
    normalize_phone,
    create_stock_for_vendeur
)
from apps import db


@bp.route("/")
def route_default():
    """Redirect root to login."""
    return redirect(url_for("auth_bp.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Login with phone number and password.

    Changes from original:
    - Uses phone number instead of username
    - Updates last_login timestamp
    """
    # Already logged in? Go to dashboard
    if current_user.is_authenticated:
        return redirect(url_for("main_bp.index"))

    form = LoginForm()

    # Handle form submission
    if form.validate_on_submit():
        # Normalize phone for lookup
        phone = normalize_phone(form.phone.data)
        user = User.query.filter_by(phone=phone).first()

        # Check if user exists
        if user is None:
            flash("Numéro de téléphone non trouvé", "danger")
            return render_template("auth/login.html", form=form)

        # Check password
        if not user.check_password(form.password.data):
            flash("Mot de passe incorrect", "danger")
            return render_template("auth/login.html", form=form)

        # Check if account is active
        if not user.is_active:
            flash("Ce compte a été désactivé. Contactez l'administrateur.", "warning")
            return render_template("auth/login.html", form=form)

        # Success! Log them in
        login_user(user, remember=form.remember_me.data)

        # Update last login time
        user.last_login = datetime.now(timezone.utc)
        db.session.commit()

        # Welcome message
        flash(f"Bienvenue, {user.username}!", "success")

        # Redirect priority: ROLE FIRST
        if user.is_platform_admin:
            return redirect(url_for('admin_bp.dashboard'))

        # Then handle next (only if useful)
        next_page = request.args.get('next')
        if next_page and urlparse(next_page).netloc == '' and next_page != '/':
            return redirect(next_page)

        # Default fallback
        return redirect(url_for('main_bp.index'))

    return render_template("auth/login.html", form=form)


@bp.route("/register", methods=["GET", "POST"])
def register():
    """
    Registration for new Vendeurs (business owners).

    Two modes:
    1. With invite code: Full registration
    2. Without invite code: Show "contact admin" message

    When a vendeur registers:
    - Their account is created
    - Stock items for all 4 networks are auto-created (balance = 0)
    """
    # Already logged in? Go to dashboard
    if current_user.is_authenticated:
        return redirect(url_for("main_bp.index"))

    # Check if invite code was provided in URL
    invite_code_from_url = request.args.get('code')

    # If no invite code provided, show info page
    if not invite_code_from_url and request.method == 'GET':
        return render_template(
            "auth/register.html",
            msg="Pour créer un compte, vous avez besoin d'un code d'invitation. Contactez l'administrateur via WhatsApp.",
            form=CreateAccountForm(),  # Use old form for template compatibility
            disabled=True,
            show_registration_form=False
        )

    # With invite code, show full registration form
    form = VendeurRegistrationForm()

    # Pre-fill invite code from URL
    if invite_code_from_url and request.method == 'GET':
        form.invite_code.data = invite_code_from_url

    if form.validate_on_submit():
        try:
            # Get and validate invite code
            invite_code = InviteCode.query.filter_by(
                code=form.invite_code.data.strip()
            ).first()

            if not invite_code or not invite_code.is_valid:
                flash("Code d'invitation invalide ou expiré", "danger")
                return render_template(
                    "auth/register.html",
                    form=form,
                    show_registration_form=True
                )

            # Create new vendeur
            normalized_phone = normalize_phone(form.phone.data)

            new_vendeur = User(
                username=form.username.data.strip(),
                phone=normalized_phone,
                email=form.email.data.strip().lower() if form.email.data else None,
                role=RoleType.VENDEUR,
                is_active=True,
            )
            new_vendeur.set_password(form.password.data)

            db.session.add(new_vendeur)
            db.session.flush()  # Get the new user ID

            # Mark invite code as used
            invite_code.used_by_id = new_vendeur.id
            invite_code.used_at = datetime.now(timezone.utc)

            # Create stock items for the new vendeur (one per network, balance 0)
            stocks = create_stock_for_vendeur(new_vendeur.id)

            db.session.commit()

            current_app.logger.info(
                f"New vendeur registered: {new_vendeur.username} (ID: {new_vendeur.id}), "
                f"created {len(stocks)} stock items"
            )

            flash(
                "Compte créé! Connectez-vous.",
                "success"
            )
            return redirect(url_for("auth_bp.login"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Registration error: {e}", exc_info=True)
            flash("Une erreur est survenue lors de la création du compte", "danger")

    return render_template(
        "auth/register.html",
        form=form,
        show_registration_form=True
    )


@bp.route("/logout")
@login_required
def logout():
    """Log out the current user."""
    username = current_user.username
    logout_user()
    flash(f"Au revoir, {username}!", "info")
    return redirect(url_for("auth_bp.login"))

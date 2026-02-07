from datetime import datetime, timezone
from flask import render_template, redirect, request, url_for, flash
from flask_login import current_user, login_user, logout_user
from apps.auth import bp
from apps.auth.forms import LoginForm, CreateAccountForm, normalize_drc_phone
from apps.models import User, db
from sqlalchemy import or_

@bp.route("/")
def route_default():
    return redirect(url_for("auth_bp.login"))


# Login & Registration
@bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        raw_phone = form.phone.data.strip()
        password = form.password.data

        normalized_phone = normalize_drc_phone(raw_phone)

        # On cherche uniquement par téléphone
        user = User.query.filter_by(phone=normalized_phone).first()

        if user and user.check_password(password):
            login_user(user)

            # Mise à jour last_login
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()

            flash("Bienvenue !", "success")
            return redirect(url_for("main_bp.index"))

        flash("Numéro ou mot de passe incorrect.", "danger")

    return render_template("auth/login.html", form=form)




@bp.route("/register", methods=["GET", "POST"])
def register():
    return render_template(
        "auth/register.html",
        msg="Contacter l'admin pour créer votre compte",
        form=CreateAccountForm(request.form),
        disabled=True,
    )



@bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth_bp.login"))

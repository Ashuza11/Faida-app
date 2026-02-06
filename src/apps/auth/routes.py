from flask import render_template, redirect, request, url_for, flash
from flask_login import current_user, login_user, logout_user
from apps.auth import bp
from apps.auth.forms import LoginForm, CreateAccountForm
from apps.models import User


@bp.route("/")
def route_default():
    return redirect(url_for("auth_bp.login"))


# Login & Registration
from sqlalchemy import or_

@bp.route("/login", methods=["GET", "POST"])
def login():
    login_form = LoginForm(request.form)
    
    # Vérification si le bouton login est pressé
    if "login" in request.form and login_form.validate():
        login_id = request.form["login_id"]
        password = request.form["password"]

        # Recherche hybride : username OU phone
        user = User.query.filter(
            or_(User.username == login_id, User.phone == login_id)
        ).first()

        if user and user.check_password(password):
            login_user(user)
            flash(f"Bienvenue {user.username} !", "success")
            return redirect(url_for("main_bp.index"))

        return render_template(
            "auth/login.html", 
            msg="Identifiants ou mot de passe incorrects", 
            form=login_form
        )

    if not current_user.is_authenticated:
        return render_template("auth/login.html", form=login_form)
        
    return redirect(url_for("main_bp.index"))


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

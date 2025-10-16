from flask import render_template, redirect, request, url_for, flash
from flask_login import current_user, login_user, logout_user
from apps.auth import bp
from apps.auth.forms import LoginForm, CreateAccountForm
from apps.models import User


@bp.route("/")
def route_default():
    return redirect(url_for("auth_bp.login"))


# Login & Registration
@bp.route("/login", methods=["GET", "POST"])
def login():
    login_form = LoginForm(request.form)
    if "login" in request.form:
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            # welcome message
            flash(f"Bienvenue {user.username} !", "success")

            # Templates will handle role-based UI
            return redirect(url_for("main_bp.index"))

        return render_template(
            "auth/login.html", msg="Identifiants invalides", form=login_form
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

from flask import render_template, redirect, request, url_for, flash
from flask_login import current_user, login_user, logout_user

from apps import db, login_manager
from apps.authentication import blueprint
from apps.authentication.forms import LoginForm, CreateAccountForm
from apps.authentication.models import User


@blueprint.route("/")
def route_default():
    return redirect(url_for("authentication_blueprint.login"))


# Login & Registration
@blueprint.route("/login", methods=["GET", "POST"])
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
            return redirect(url_for("home_blueprint.index"))

        return render_template(
            "accounts/login.html", msg="Identifiants invalides", form=login_form
        )

    if not current_user.is_authenticated:
        return render_template("accounts/login.html", form=login_form)
    return redirect(url_for("home_blueprint.index"))


@blueprint.route("/register", methods=["GET", "POST"])
def register():
    return render_template(
        "accounts/register.html",
        msg="Contacter l'admin pour créer votre compte",
        form=CreateAccountForm(request.form),
        disabled=True,
    )


@blueprint.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("authentication_blueprint.login"))

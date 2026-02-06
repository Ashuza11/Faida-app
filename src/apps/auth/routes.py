from flask import render_template, redirect, request, url_for, flash
from flask_login import current_user, login_user, logout_user
from apps.auth import bp
from apps.auth.forms import LoginForm, CreateAccountForm, normalize_drc_phone
from apps.models import User
from sqlalchemy import or_

@bp.route("/")
def route_default():
    return redirect(url_for("auth_bp.login"))


# Login & Registration
@bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()

    print("METHOD:", request.method)

    if request.method == "POST":
        print("RAW FORM:", request.form)

    if request.method == "POST" and not form.validate():
        print("FORM ERRORS:", form.errors)

    if form.validate_on_submit():
        print("VALIDATED OK")

        login_id = form.login_id.data.strip()
        password = form.password.data

        normalized_phone = normalize_drc_phone(login_id)

        user = User.query.filter(
            or_(
                User.username == login_id,
                User.phone == normalized_phone,
            )
        ).first()

        if user and user.check_password(password):
            login_user(user)
            flash(f"Bienvenue {user.username} !", "success")
            return redirect(url_for("main_bp.index"))

        print("BAD CREDENTIALS")
        flash("Identifiants ou mot de passe incorrects", "danger")

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

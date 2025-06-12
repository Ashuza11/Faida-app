from apps.home import blueprint
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from jinja2 import TemplateNotFound
from apps.decorators import superadmin_required, vendeur_required
from apps import db
from apps.authentication.models import User, RoleType
from apps.home.forms import StockerForm


@blueprint.route("/index")
@login_required
def index():

    return render_template("home/index.html", segment="index")


@blueprint.route("/<template>")
@login_required
def route_template(template):

    try:

        if not template.endswith(".html"):
            template += ".html"

        # Detect the current page
        segment = get_segment(request)

        # Serve the file (if exists) from app/templates/home/FILE.html
        return render_template("home/" + template, segment=segment)

    except TemplateNotFound:
        return render_template("home/page-404.html"), 404

    except:
        return render_template("home/page-500.html"), 500


# Helper - Extract current page name from request
def get_segment(request):

    try:

        segment = request.path.split("/")[-1]

        if segment == "":
            segment = "index"

        return segment

    except:
        return None


# User management
@blueprint.route("/admin/stocker", methods=["GET", "POST"])
@login_required
@superadmin_required
def stocker_management():
    """
    Renders the stocker management page and handles creation of new users (stocker).
    """
    stocker_form = StockerForm()
    print("I am makuga ")

    # Handle the form submission for creating a new stocker
    if stocker_form.validate_on_submit():
        print("I am makuga one two")
        # Check if username or email already exists
        existing_user = User.query.filter(
            (User.username == stocker_form.username.data)
            | (User.email == stocker_form.email.data)
        ).first()

        if existing_user:
            flash("Username or email in use.", "danger")
        else:
            new_user = User(
                username=stocker_form.username.data,
                email=stocker_form.email.data,
                role=RoleType(stocker_form.role.data),
                created_by=current_user.id,
            )
            new_user.set_password(stocker_form.password.data)
            db.session.add(new_user)
            db.session.commit()
            flash("User created successfully!", "success")
            return redirect(url_for("home_blueprint.stocker_management"))

    users = User.query.all()
    return render_template(
        "home/user.html",
        users=users,
        stocker_form=stocker_form,
        segment="admin",
        sub_segment="stocker",
    )


@blueprint.route("/admin/client")
@login_required
@superadmin_required
@vendeur_required
def client_management():
    clients = []
    return render_template(
        "home/clients.html",
        users=clients,
        segment="admin",
        sub_segment="client",
    )


@blueprint.route("/api/add_stocker", methods=["POST"])
@login_required
@superadmin_required
def add_stocker():
    data = request.get_json()

    try:
        # Create new stocker
        stocker = User(
            username=data["username"],
            email=data["email"],
            role=RoleType.VENDEUR,
            is_active=True,
        )
        stocker.set_password(data["password"])
        stocker.created_by = current_user.id

        db.session.add(stocker)
        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": "Stocker added successfully",
                "stocker": {
                    "id": stocker.id,
                    "username": stocker.username,
                    "email": stocker.email,
                },
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 400

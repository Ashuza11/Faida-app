from apps.home import blueprint
from flask import render_template, request, flash, redirect, url_for, abort, current_app
from flask_login import login_required, current_user
from jinja2 import TemplateNotFound
from apps.decorators import superadmin_required, vendeur_required
from apps import db
from apps.authentication.models import (
    User,
    RoleType,
    Client,
    StockPurchase,
    NetworkType,
    Stock,
)
from apps.home.forms import (
    StockerForm,
    UserEditForm,
    ClientForm,
    ClientEditForm,
    StockPurchaseForm,
)


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

        segment = get_segment(request)
        return render_template("home/" + template, segment=segment)

    except TemplateNotFound:
        abort(404)  # Triggers the  global @app.errorhandler(404)

    except Exception as e:
        print(f"An unexpected error occurred in route_template: {e}")  # Log the error
        abort(500)  # Triggers the global @app.errorhandler(500)


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
    user_edit_form = UserEditForm()

    # Handle the form submission for creating a new stocker
    if stocker_form.validate_on_submit():
        # Check if username or email already exists
        existing_user = User.query.filter(
            (User.username == stocker_form.username.data)
            | (User.email == stocker_form.email.data)
        ).first()

        if existing_user:
            flash("Nom d'utilisateur ou email déjà utilisé.", "danger")
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
            flash("Utilisateur créé avec succès!", "success")
            return redirect(url_for("home_blueprint.stocker_management"))

    users = User.query.all()
    return render_template(
        "home/user.html",
        users=users,
        stocker_form=stocker_form,
        user_edit_form=user_edit_form,
        segment="admin",
        sub_segment="stocker",
    )


@blueprint.route("/admin/user/edit/<int:user_id>", methods=["GET", "POST"])
@login_required
@superadmin_required
def user_edit(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("Utilisateur non trouvé.", "danger")
        return redirect(url_for("home_blueprint.stocker_management"))

    user_edit_form = UserEditForm()
    stocker_form = StockerForm()

    if user_edit_form.validate_on_submit():
        # Check if username or email already exists for *another* user
        existing_user_by_username = User.query.filter(
            User.username == user_edit_form.username.data, User.id != user_id
        ).first()
        existing_user_by_email = User.query.filter(
            User.email == user_edit_form.email.data, User.id != user_id
        ).first()

        if existing_user_by_username:
            flash("Nom d'utilisateur déjà utilisé", "danger")
        elif existing_user_by_email:
            flash("Email déjà utilisé ", "danger")
        else:
            user.username = user_edit_form.username.data
            user.email = user_edit_form.email.data
            user.role = RoleType(user_edit_form.role.data)
            user.is_active = user_edit_form.is_active.data
            db.session.commit()
            flash("Utilisateur mis à jour avec succès!", "success")
            return redirect(url_for("home_blueprint.stocker_management"))
    elif request.method == "GET":
        # Pre-populate form with existing user data on GET request
        user_edit_form.username.data = user.username
        user_edit_form.email.data = user.email
        user_edit_form.role.data = user.role.value
        user_edit_form.is_active.data = user.is_active

    users = User.query.all()
    return render_template(
        "home/user.html",
        users=users,
        stocker_form=stocker_form,
        user_edit_form=user_edit_form,
        segment="admin",
        sub_segment="stocker",
    )


@blueprint.route("/admin/user/toggle_active/<int:user_id>", methods=["POST"])
@login_required
@superadmin_required
def user_toggle_active(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("Utilisateur non trouvé.", "danger")
    else:
        # Prevent deactivating the superadmin who is currently logged in
        if user.id == current_user.id and user.role == RoleType.SUPERADMIN:
            flash("Impossible de désactiver votre compte", "warning")
        else:
            user.is_active = not user.is_active  # Toggle the status
            db.session.commit()
            if user.is_active:
                flash(f"Utilisateur '{user.username}' activé avec succès!", "success")
            else:
                flash(
                    f"Utilisateur '{user.username}' désactivé avec succès!", "success"
                )
    return redirect(url_for("home_blueprint.stocker_management"))


# Client Management
@blueprint.route("/admin/clients", methods=["GET", "POST"])
@login_required
@vendeur_required
def client_management():
    """
    Renders the client management page and handles creation of new clients.
    """
    client_form = ClientForm()
    client_edit_form = ClientEditForm()

    if client_form.validate_on_submit():
        # Retrieve GPS data directly from request.form as it's no longer part of WTForms
        # Use .get() to safely retrieve, in case the values are not present
        gps_lat = request.form.get("gps_lat")
        gps_long = request.form.get("gps_long")

        # Convert to float if not None
        try:
            gps_lat = float(gps_lat) if gps_lat else None
            gps_long = float(gps_long) if gps_long else None
        except ValueError:
            flash("Coordonnées GPS invalides.", "danger")
            # If conversion fails, you might want to render the template again
            # with existing form data to show error, or set to None
            gps_lat = None
            gps_long = None

        existing_client = Client.query.filter_by(name=client_form.name.data).first()

        if existing_client:
            flash("Un client avec ce nom existe déjà.", "danger")
        else:
            new_client = Client(
                name=client_form.name.data,
                # email=client_form.email.data if client_form.email.data else None,
                phone_airtel=client_form.phone_airtel.data,
                phone_africel=client_form.phone_africel.data,
                phone_orange=client_form.phone_orange.data,
                phone_vodacom=client_form.phone_vodacom.data,
                address=client_form.address.data,
                gps_lat=gps_lat,  # Use the retrieved GPS data
                gps_long=gps_long,  # Use the retrieved GPS data
                discount_rate=client_form.discount_rate.data,
                vendeur=current_user,
            )
            db.session.add(new_client)
            db.session.commit()
            flash("Client créé avec succès!", "success")
            return redirect(url_for("home_blueprint.client_management"))

    # Query clients
    if current_user.role == RoleType.SUPERADMIN:
        clients = Client.query.all()
    else:
        clients = Client.query.filter_by(vendeur_id=current_user.id).all()

    return render_template(
        "home/clients.html",
        clients=clients,
        client_form=client_form,
        client_edit_form=client_edit_form,
        segment="admin",
        sub_segment="clients",
    )


@blueprint.route("/admin/clients/edit/<int:client_id>", methods=["POST"])
@login_required
@vendeur_required
def client_edit(client_id):
    """
    Handles editing of client information.
    """
    client = Client.query.get_or_404(client_id)

    # Authorization check: Vendeur can only edit their own clients
    if (
        current_user.role != RoleType.SUPERADMIN
        and client.vendeur_id != current_user.id
    ):
        flash("Vous n'êtes pas autorisé à modifier ce client.", "danger")
        return redirect(url_for("home_blueprint.client_management"))

    client_edit_form = ClientEditForm()
    if client_edit_form.validate_on_submit():
        client.name = client_edit_form.name.data
        client.email = (
            client_edit_form.email.data if client_edit_form.email.data else None
        )
        client.phone_airtel = client_edit_form.phone_airtel.data
        client.phone_africel = client_edit_form.phone_africel.data
        client.phone_orange = client_edit_form.phone_orange.data
        client.phone_vodacom = client_edit_form.phone_vodacom.data
        client.address = client_edit_form.address.data
        client.gps_lat = client_edit_form.gps_lat.data
        client.gps_long = client_edit_form.gps_long.data
        client.is_active = client_edit_form.is_active.data
        client.discount_rate = client_edit_form.discount_rate.data

        db.session.commit()
        flash("Client mis à jour avec succès!", "success")
        return redirect(url_for("home_blueprint.client_management"))
    else:
        # If validation fails, repopulate the form with existing data and show errors
        # This is where the modal JS will pick up errors and reopen the modal
        flash(
            "Erreur lors de la mise à jour du client. Veuillez vérifier les champs.",
            "danger",
        )
        # Pre-populate form for re-rendering if validation fails (important for modal)
        # This part is handled by the data attributes in the JS when the modal is re-opened.
        # However, if you redirect with errors, you might want to flash them more specifically.
    return redirect(url_for("home_blueprint.client_management"))


@blueprint.route("/admin/clients/toggle-active/<int:client_id>", methods=["POST"])
@login_required
@vendeur_required
def client_toggle_active(client_id):
    """
    Toggles the active status of a client.
    """
    client = Client.query.get_or_404(client_id)

    # Authorization check: Vendeur can only toggle their own clients
    if (
        current_user.role != RoleType.SUPERADMIN
        and client.vendeur_id != current_user.id
    ):
        flash("Vous n'êtes pas autorisé à modifier le statut de ce client.", "danger")
        return redirect(url_for("home_blueprint.client_management"))

    client.is_active = not client.is_active
    db.session.commit()
    status_message = "activé" if client.is_active else "désactivé"
    flash(f"Client {client.name} {status_message} avec succès!", "success")
    return redirect(url_for("home_blueprint.client_management"))


@blueprint.route("/achat_stock", methods=["GET", "POST"])
@login_required
@superadmin_required
def Achat_stock():
    segment = "stock"
    sub_segment = "Achat_stock"

    form = StockPurchaseForm()

    if form.validate_on_submit():
        network = NetworkType(form.network.data)
        amount_purchased = form.amount_purchased.data

        try:
            # --- FIX STARTS HERE ---

            # Find or create the Stock item for the given network
            stock_item = Stock.query.filter_by(network=network).first()
            if not stock_item:
                # If for some reason it doesn't exist (e.g., initial_stock_items didn't run,
                # or new network added after app creation without restart)
                stock_item = Stock(
                    network=network,
                    balance=0.00,  # Start with 0 balance
                    selling_price_per_unit=1.00,
                    reduction_rate=0.00,
                )
                db.session.add(stock_item)
                # It's important to flush here so stock_item gets an ID before StockPurchase uses it
                db.session.flush()

            # Record the StockPurchase and link it directly to the stock_item object
            new_purchase = StockPurchase(
                network=network,  # Denormalized
                amount_purchased=amount_purchased,
                purchased_by=current_user,
                stock_item=stock_item,  # <-- Assign the Stock object directly here!
            )
            db.session.add(new_purchase)

            # Now update the balance of the existing (or newly created) stock_item
            stock_item.balance += amount_purchased

            # Commit both the new purchase and the updated stock_item
            db.session.commit()
            flash(
                f"Successfully registered {amount_purchased} FC of {network.value} stock.",
                "success",
            )
            return redirect(url_for("home_blueprint.Achat_stock"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error registering stock purchase: {e}")
            flash(
                f"An error occurred while registering the purchase: {e}. Please try again.",
                "danger",
            )  # Show more specific error for debug

    # Fetch existing stock purchases for display
    stock_purchases = StockPurchase.query.order_by(
        StockPurchase.created_at.desc()
    ).all()

    return render_template(
        "home/achat_stock.html",
        form=form,
        stock_purchases=stock_purchases,
        segment=segment,
        sub_segment=sub_segment,
    )

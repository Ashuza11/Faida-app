from apps.home import blueprint
from flask import render_template, request, flash, redirect, url_for, abort, current_app
from flask_login import login_required, current_user
from jinja2 import TemplateNotFound
from apps.decorators import superadmin_required, vendeur_required
from apps.home.utils import custom_round_up
from apps import db
from decimal import Decimal, InvalidOperation
from datetime import datetime, date
from sqlalchemy import func
from apps.authentication.models import (
    User,
    RoleType,
    Client,
    StockPurchase,
    NetworkType,
    Stock,
    RoleType,
    User,
    Sale,
    SaleItem,
    CashOutflow,
    CashInflow,
    CashOutflowCategory,
    CashInflowCategory,
    DailyOverallReport,
    DailyStockReport,
)

from apps.home.forms import (
    StockerForm,
    UserEditForm,
    ClientForm,
    ClientEditForm,
    StockPurchaseForm,
    SaleForm,
    CashOutflowForm,
    DebtCollectionForm,
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
        abort(404)
    except Exception as e:
        print(f"An unexpected error occurred in route_template: {e}")
        abort(500)


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
    form = StockPurchaseForm()

    if form.validate_on_submit():
        try:
            network_type_string_from_form = form.network.data
            try:
                network_enum = NetworkType(network_type_string_from_form.lower())
            except ValueError:
                flash(
                    f"Le type de réseau '{network_type_string_from_form}' n'est pas valide.",
                    "danger",
                )
                # Reload data for the template if validation fails
                stock_purchases = StockPurchase.query.order_by(
                    StockPurchase.created_at.desc()
                ).all()
                return render_template(
                    "home/achat_stock.html",
                    stock_purchases=stock_purchases,
                    form=form,
                    segment="stock",
                    sub_segment="Achat_stock",
                )

            amount_purchased = form.amount_purchased.data

            buying_price_to_record = None
            if form.buying_price_choice.data == "custom":
                buying_price_to_record = form.custom_buying_price.data
            elif form.buying_price_choice.data:
                buying_price_to_record = Decimal(form.buying_price_choice.data)

            selling_price_to_record = None
            if form.intended_selling_price_choice.data == "custom":
                selling_price_to_record = form.custom_intended_selling_price.data
            elif form.intended_selling_price_choice.data:
                selling_price_to_record = Decimal(
                    form.intended_selling_price_choice.data
                )

            # Validate that both prices are determined
            if buying_price_to_record is None or selling_price_to_record is None:
                flash(
                    "Veuillez sélectionner ou entrer un prix d'achat et un prix de vente.",
                    "danger",
                )
                # Reload data for the template and render
                stock_purchases = StockPurchase.query.order_by(
                    StockPurchase.created_at.desc()
                ).all()
                return render_template(
                    "home/achat_stock.html",
                    stock_purchases=stock_purchases,
                    form=form,
                    segment="stock",
                    sub_segment="Achat_stock",
                )

            # --- Database Operations ---
            stock_item = Stock.query.filter_by(network=network_enum).first()

            if stock_item:
                stock_item.balance += amount_purchased
                stock_item.buying_price_per_unit = buying_price_to_record
                stock_item.selling_price_per_unit = selling_price_to_record
            else:
                stock_item = Stock(
                    network=network_enum,
                    balance=amount_purchased,
                    buying_price_per_unit=buying_price_to_record,
                    selling_price_per_unit=selling_price_to_record,
                    reduction_rate=Decimal("0.00"),
                )
                db.session.add(stock_item)

            db.session.flush()

            new_purchase = StockPurchase(
                stock_item_id=stock_item.id,
                network=network_enum,
                amount_purchased=amount_purchased,
                buying_price_at_purchase=buying_price_to_record,
                selling_price_at_purchase=selling_price_to_record,
                purchased_by=current_user,
            )
            db.session.add(new_purchase)
            db.session.commit()

            flash("Achat de stock enregistré avec succès!", "success")
            return redirect(url_for("home_blueprint.Achat_stock"))

        except Exception as e:
            # --- General Error Handling (Database or unexpected server errors) ---
            db.session.rollback()
            current_app.logger.error(f"Error recording stock purchase: {e}")
            flash(
                f"Une erreur est survenue lors de l'enregistrement de l'achat: {e}",
                "danger",
            )
            # Re-render the form with the error message and current data
            stock_purchases = StockPurchase.query.order_by(
                StockPurchase.created_at.desc()
            ).all()
            return render_template(
                "home/achat_stock.html",
                stock_purchases=stock_purchases,
                form=form,
                segment="stock",
                sub_segment="Achat_stock",
            )

    stock_purchases = StockPurchase.query.order_by(
        StockPurchase.created_at.desc()
    ).all()
    return render_template(
        "home/achat_stock.html",
        stock_purchases=stock_purchases,
        form=form,
        segment="stock",
        sub_segment="Achat_stock",
    )


# Edit Stock Purchase
@blueprint.route("/achat_stock/editer/<int:purchase_id>", methods=["GET", "POST"])
@login_required
@superadmin_required
def edit_stock_purchase(purchase_id):
    purchase = StockPurchase.query.get_or_404(purchase_id)
    form = StockPurchaseForm(obj=purchase)

    # --- Pre-fill form based on existing purchase data ---
    # Pre-fill Buying Price choice
    if purchase.buying_price_at_purchase == Decimal("26.79"):
        form.buying_price_choice.data = "26.79"
        form.custom_buying_price.data = None
    elif purchase.buying_price_at_purchase == Decimal(
        "27.075"
    ):  # Match your form choices
        form.buying_price_choice.data = "27.075"
        form.custom_buying_price.data = None
    else:
        form.buying_price_choice.data = "custom"
        form.custom_buying_price.data = purchase.buying_price_at_purchase

    # Pre-fill Selling Price choice
    if purchase.selling_price_at_purchase == Decimal("27.5"):
        form.intended_selling_price_choice.data = "27.5"
        form.custom_intended_selling_price.data = None
    elif purchase.selling_price_at_purchase == Decimal(
        "28.0"
    ):  # Match your form choices
        form.intended_selling_price_choice.data = "28.0"
        form.custom_intended_selling_price.data = None
    else:
        form.intended_selling_price_choice.data = "custom"
        form.custom_intended_selling_price.data = purchase.selling_price_at_purchase

    if form.validate_on_submit():
        try:
            old_amount_purchased = purchase.amount_purchased
            old_network = purchase.network

            network_enum_value = form.network.data
            network_enum = NetworkType(network_enum_value)
            amount_purchased = form.amount_purchased.data

            # Determine BUYING price from the form
            buying_price_to_record = None
            if form.buying_price_choice.data == "custom":
                buying_price_to_record = form.custom_buying_price.data
            elif form.buying_price_choice.data:
                buying_price_to_record = Decimal(form.buying_price_choice.data)

            # Determine SELLING price from the form
            selling_price_to_record = None
            if form.intended_selling_price_choice.data == "custom":
                selling_price_to_record = form.custom_intended_selling_price.data
            elif form.intended_selling_price_choice.data:
                selling_price_to_record = Decimal(
                    form.intended_selling_price_choice.data
                )

            # Re-validate prices (though form.validate_on_submit() should catch this)
            if buying_price_to_record is None or selling_price_to_record is None:
                flash(
                    "Veuillez sélectionner ou entrer un prix d'achat et un prix de vente valides.",
                    "danger",
                )
                return render_template(
                    "home/edit_stock_purchase.html",
                    form=form,
                    purchase=purchase,
                    page_title="Editer Achat de Stock",
                    segment="stock",
                    sub_segment="Achat_stock",
                )

            # Update the StockPurchase record itself
            purchase.network = network_enum
            purchase.amount_purchased = amount_purchased
            purchase.buying_price_at_purchase = buying_price_to_record  # NEW
            purchase.selling_price_at_purchase = selling_price_to_record  # UPDATED
            purchase.updated_at = datetime.utcnow()

            # --- Adjust Stock Balance and Buying/Selling Prices on Stock model ---
            # Step 1: Revert old amount from old network's stock
            old_stock_item = Stock.query.filter_by(network=old_network).first()
            if old_stock_item:
                old_stock_item.balance -= old_amount_purchased
                db.session.add(old_stock_item)

            # Step 2: Apply new amount to new network's stock, and update its current prices
            new_stock_item = Stock.query.filter_by(network=network_enum).first()
            if new_stock_item:
                new_stock_item.balance += amount_purchased
                # Update the buying_price_per_unit in the Stock table for the new (or same) network
                new_stock_item.buying_price_per_unit = (
                    buying_price_to_record  # Corrected here
                )
                # Update the selling_price_per_unit in the Stock table for the new (or same) network
                new_stock_item.selling_price_per_unit = selling_price_to_record  # NEW
                db.session.add(new_stock_item)
            else:
                new_stock_item = Stock(
                    network=network_enum,
                    balance=amount_purchased,
                    buying_price_per_unit=buying_price_to_record,  # Corrected here
                    selling_price_per_unit=selling_price_to_record,  # NEW
                    reduction_rate=Decimal("0.00"),
                )
                db.session.add(new_stock_item)

            db.session.commit()
            flash("Achat de stock mis à jour avec succès!", "success")
            return redirect(url_for("home_blueprint.Achat_stock"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error updating stock purchase {purchase_id}: {e}"
            )
            flash(f"Une erreur est survenue lors de la mise à jour: {e}", "danger")

    return render_template(
        "home/edit_stock_purchase.html",
        form=form,
        purchase=purchase,
        page_title="Editer Achat de Stock",
        segment="stock",
        sub_segment="Achat_stock",
    )


# Delete Stock Purchase
@blueprint.route("/achat_stock/supprimer/<int:purchase_id>", methods=["GET", "POST"])
@login_required
@superadmin_required
def delete_stock_purchase(purchase_id):
    purchase = StockPurchase.query.get_or_404(purchase_id)

    if request.method == "POST":
        try:
            # Revert the stock balance
            stock_item = Stock.query.filter_by(network=purchase.network).first()
            if stock_item:
                stock_item.balance -= purchase.amount_purchased
                # Note: deleting a purchase does not adjust buying_price_per_unit/selling_price_per_unit
                # on Stock because those reflect the *latest* purchase. If the deleted purchase was
                # the latest, these prices on Stock might become "stale" until a new purchase occurs.
                # A more complex system might look for the next latest purchase to update them,
                # but for simplicity, we leave them as is.
                db.session.add(stock_item)
            else:
                flash(
                    "Erreur: L'article de stock correspondant est introuvable.",
                    "danger",
                )
                return redirect(url_for("home_blueprint.Achat_stock"))

            db.session.delete(purchase)
            db.session.commit()
            flash(f"Achat de stock #{purchase_id} supprimé avec succès!", "success")
            return redirect(url_for("home_blueprint.Achat_stock"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error deleting stock purchase {purchase_id}: {e}"
            )
            flash(f"Une erreur est survenue lors de la suppression: {e}", "danger")
            return redirect(url_for("home_blueprint.Achat_stock"))

    flash("Confirmez la suppression de l'achat de stock.", "warning")
    return render_template(
        "home/confirm_delete_stock_purchase.html",
        purchase=purchase,
        page_title="Confirmer Suppression",
        segment="stock",
        sub_segment="Achat_stock",
    )


@blueprint.route("/vente_stock", methods=["GET", "POST"])
@login_required
@superadmin_required
@vendeur_required
def vente_stock():
    form = SaleForm()

    # IMPORTANT FIX: Set choices for existing_client_id field HERE
    clients = Client.query.filter_by(is_active=True).order_by(Client.name).all()
    client_choices = [("", "Sélectionnez un client existant")]
    client_choices.extend([(str(client.id), client.name) for client in clients])
    form.existing_client_id.choices = client_choices

    # Populate sale_items FieldList with initial empty forms for GET requests
    if request.method == "GET" and not form.sale_items:
        for _ in range(3):
            form.sale_items.append_entry()

    if form.validate_on_submit():
        client = None
        client_name_adhoc = None

        # Determine client based on choice
        if form.client_choice.data == "existing":
            client_id = form.existing_client_id.data
            if client_id:
                client = Client.query.get(int(client_id))
                if not client:
                    flash("Client existant sélectionné invalide.", "danger")
                    return render_template(
                        "home/vente_stock.html",
                        form=form,
                        segment="stock",
                        sub_segment="vente_stock",
                    )
            else:
                flash("Veuillez sélectionner un client existant.", "danger")
                return render_template(
                    "home/vente_stock.html",
                    form=form,
                    segment="stock",
                    sub_segment="vente_stock",
                )
        elif form.client_choice.data == "new":
            client_name_adhoc = form.new_client_name.data
            if not client_name_adhoc:
                flash("Veuillez entrer le nom du nouveau client.", "danger")
                return render_template(
                    "home/vente_stock.html",
                    form=form,
                    segment="stock",
                    sub_segment="vente_stock",
                )

        total_amount_due = Decimal("0.00")
        sale_items_to_add = []
        errors_during_sale = []

        # Process each sale item
        for item_data in form.sale_items.entries:
            # Ensure each individual SaleItemForm also validates its data
            if not item_data.form.validate():
                for field_name, field_errors in item_data.form.errors.items():
                    for error in field_errors:
                        errors_during_sale.append(
                            f"Erreur dans l'article {item_data.id}: {item_data.form[field_name].label.text}: {error}"
                        )
                continue

            network_type = NetworkType[item_data.form.network.data]
            quantity = item_data.form.quantity.data
            price_per_unit_applied_from_form = (
                item_data.form.price_per_unit_applied.data
            )  # Get from form

            # Fetch stock to ensure it exists and to calculate subtotal
            stock_item = Stock.query.filter_by(network=network_type).first()

            if not stock_item:
                flash(f"Réseau '{network_type.value}' non trouvé en stock.", "danger")
                continue

            if quantity > stock_item.balance:
                errors_during_sale.append(
                    f"Quantité insuffisante pour {network_type.value}. Disponible: {stock_item.balance}, Demandé: {quantity}."
                )
                continue

            # Determine the selling price to use for this sale item
            final_price_per_unit_for_sale_item = None
            if price_per_unit_applied_from_form is not None:
                final_price_per_unit_for_sale_item = price_per_unit_applied_from_form
            elif (
                stock_item.selling_price_per_unit is not None
                and stock_item.selling_price_per_unit > 0
            ):
                final_price_per_unit_for_sale_item = stock_item.selling_price_per_unit
            else:
                errors_during_sale.append(
                    f"Impossible de déterminer le prix unitaire pour '{network_type.value}'. Veuillez entrer un prix manuellement ou vérifier le stock."
                )
                continue

            # Calculate subtotal using the determined price
            subtotal_unrounded = quantity * final_price_per_unit_for_sale_item
            subtotal = custom_round_up(
                subtotal_unrounded
            )  # Assuming custom_round_up function exists

            # Create SaleItem object
            new_sale_item = SaleItem(
                network=network_type,
                quantity=quantity,
                price_per_unit_applied=final_price_per_unit_for_sale_item,
                subtotal=subtotal,
            )
            sale_items_to_add.append(new_sale_item)
            total_amount_due += subtotal

            # Update stock balance immediately
            stock_item.balance -= quantity
            db.session.add(stock_item)

        if errors_during_sale:
            db.session.rollback()
            for error in errors_during_sale:
                flash(error, "error")
            return render_template(
                "home/vente_stock.html",
                form=form,
                segment="stock",
                sub_segment="vente_stock",
            )

        if not sale_items_to_add:
            flash("Veuillez ajouter au moins un article à la vente.", "danger")
            return render_template(
                "home/vente_stock.html",
                form=form,
                segment="stock",
                sub_segment="vente_stock",
            )

        cash_paid = (
            form.cash_paid.data if form.cash_paid.data is not None else Decimal("0.00")
        )
        debt_amount = total_amount_due - cash_paid
        if debt_amount < 0:
            flash("L'argent donné ne peut pas dépasser le montant total dû.", "danger")
            return render_template(
                "home/vente_stock.html",
                form=form,
                segment="stock",
                sub_segment="vente_stock",
            )

        new_sale = Sale(
            vendeur=current_user,
            client=client,
            client_name_adhoc=client_name_adhoc if not client else None,
            total_amount_due=total_amount_due,
            cash_paid=cash_paid,
            debt_amount=debt_amount,
        )

        new_sale.sale_items.extend(sale_items_to_add)
        try:
            db.session.add(new_sale)
            db.session.commit()
            flash("Vente enregistrée avec succès!", "success")
            return redirect(url_for("home_blueprint.vente_stock"))
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de l'enregistrement de la vente: {e}", "danger")
            print(f"Error saving sale: {e}")
    else:
        # This block executes if form.validate_on_submit() is False
        for field, errors in form.errors.items():
            for error in errors:
                # Flash errors from main form
                flash(f"Error in {form[field].label.text}: {error}", "danger")

        # Check errors on nested FieldList forms
        for i, entry in enumerate(form.sale_items.entries):
            if entry.form.errors:
                for field_name, field_errors in entry.form.errors.items():
                    for error in field_errors:
                        # Flash errors from subforms
                        flash(
                            f"Erreur article {i+1} - {entry.form[field_name].label.text}: {error}",
                            "danger",
                        )

    sales = Sale.query.order_by(Sale.created_at.desc()).all()

    return render_template(
        "home/vente_stock.html",
        form=form,
        sales=sales,
        segment="stock",
        sub_segment="vente_stock",
    )


@blueprint.route("/update-sale-cash/<int:sale_id>", methods=["POST"])
@login_required
@superadmin_required
@vendeur_required
def update_sale_cash(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    try:
        # new_cash is directly from the input named 'new_cash'
        new_cash = Decimal(request.form.get("new_cash", "0.00"))
    except InvalidOperation:
        flash("Paiement invalide.", "danger")
        return redirect(url_for("home_blueprint.vente_stock"))

    if new_cash < 0:
        flash("Le paiement ne peut pas être négatif.", "danger")
        return redirect(url_for("home_blueprint.vente_stock"))

    # Calculate new debt
    new_debt = sale.total_amount_due - new_cash

    if new_debt < 0:
        flash("Le paiement ne peut pas dépasser le montant total dû.", "danger")
        return redirect(url_for("home_blueprint.vente_stock"))

    sale.cash_paid = new_cash
    sale.debt_amount = new_debt
    sale.updated_at = datetime.utcnow()

    try:
        db.session.commit()
        flash("Paiement mis à jour avec succès!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de la mise à jour: {e}", "danger")
        print(f"Error updating cash: {e}")

    return redirect(url_for("home_blueprint.vente_stock"))


@blueprint.route("/edit_sale/<int:sale_id>", methods=["GET", "POST"])
@login_required
@superadmin_required
def edit_sale(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    form = SaleForm()

    # Populate client choices (same as vente_stock)
    clients = Client.query.filter_by(is_active=True).order_by(Client.name).all()
    client_choices = [("", "Sélectionnez un client existant")]
    client_choices.extend([(str(client.id), client.name) for client in clients])
    form.existing_client_id.choices = client_choices

    if request.method == "GET":
        # Pre-populate the form with existing sale data
        if sale.client:
            form.client_choice.data = "existing"
            form.existing_client_id.data = str(sale.client.id)
        else:
            form.client_choice.data = "new"
            form.new_client_name.data = sale.client_name_adhoc

        # Populate SaleItems FieldList
        # Clear any existing empty entries that might have been appended by default
        while len(form.sale_items) > 0:
            form.sale_items.pop_entry()

        for item in sale.sale_items:
            # Append a new entry and populate it
            item_form = form.sale_items.append_entry()
            item_form.network.data = item.network.name  # Use .name for Enum
            item_form.quantity.data = item.quantity
            item_form.price_per_unit_applied.data = item.price_per_unit_applied
            # If you re-introduce reduction_rate_applied, populate it here too

        form.cash_paid.data = sale.cash_paid

    if form.validate_on_submit():
        # --- Start Transaction for Atomicity ---
        # This is critical for complex updates involving multiple models and stock.
        # If any step fails, we must revert all changes.
        db.session.begin_nested()  # Start a nested transaction / savepoint

        try:
            # 1. Revert old stock changes:
            # Iterate through current sale_items, add their quantities back to stock
            for old_item in sale.sale_items:
                old_stock_item = Stock.query.filter_by(network=old_item.network).first()
                if old_stock_item:
                    old_stock_item.balance += old_item.quantity
                    db.session.add(old_stock_item)
                    print(
                        f"Reverted stock for {old_item.network.value}: New balance is {old_stock_item.balance}"
                    )

            # 2. Delete old SaleItems:
            # Using cascade="all, delete-orphan" on the relationship is cleaner,
            # but explicitly deleting ensures they are removed before new ones are added.
            for item_to_delete in sale.sale_items:
                db.session.delete(item_to_delete)
            # Make sure sale.sale_items is refreshed/cleared after deletion for new items to be added clean
            sale.sale_items = (
                []
            )  # Important: Clear the relationship on the parent object

            # 3. Update Sale header data
            client = None
            client_name_adhoc = None
            if form.client_choice.data == "existing":
                client_id = form.existing_client_id.data
                if client_id:
                    client = Client.query.get(int(client_id))
                    if not client:
                        raise ValueError("Client existant sélectionné invalide.")
                else:
                    raise ValueError("Veuillez sélectionner un client existant.")
            elif form.client_choice.data == "new":
                client_name_adhoc = form.new_client_name.data
                if not client_name_adhoc:
                    raise ValueError("Veuillez entrer le nom du nouveau client.")

            sale.client = client
            sale.client_name_adhoc = client_name_adhoc if not client else None
            sale.updated_at = datetime.utcnow()

            total_amount_due = Decimal("0.00")
            sale_items_to_add = []
            errors_during_sale = []  # Collect errors for a single flash message later

            # 4. Process new sale items (similar to original vente_stock logic)
            for item_data in form.sale_items.entries:
                if not item_data.form.validate():
                    for field_name, field_errors in item_data.form.errors.items():
                        for error in field_errors:
                            errors_during_sale.append(
                                f"Erreur dans l'article: {item_data.form[field_name].label.text}: {error}"
                            )
                    continue

                network_type = NetworkType[item_data.form.network.data]
                quantity = item_data.form.quantity.data
                price_per_unit_applied = item_data.form.price_per_unit_applied.data

                stock_item = Stock.query.filter_by(network=network_type).first()

                if not stock_item:
                    errors_during_sale.append(
                        f"Réseau '{network_type.value}' non trouvé en stock."
                    )
                    continue

                if quantity > stock_item.balance + (
                    old_item.quantity if old_item.network == network_type else 0
                ):
                    # For edit, balance check must account for stock reverted from the same item
                    # This is a simplified check. More robust would be to track old quantities per network.
                    # For simplicity, if editing the same network, add back its original quantity before checking.
                    # This logic needs careful consideration if quantities change across networks within the same sale.
                    # A more robust approach might be to calculate net change in stock.
                    # For now, let's assume we reverted all old quantities, so balance is correct.
                    if (
                        quantity > stock_item.balance
                    ):  # This check is now after reversion
                        errors_during_sale.append(
                            f"Quantité insuffisante pour {network_type.value}. Disponible: {stock_item.balance}, Demandé: {quantity}."
                        )
                        continue

                # Determine the price_per_unit_applied (from previous logic)
                if price_per_unit_applied is None:
                    if stock_item.price_per_unit_applied is not None:
                        price_per_unit_applied = stock_item.price_per_unit_applied
                    else:
                        latest_purchase = (
                            StockPurchase.query.filter_by(stock_item=stock_item)
                            .order_by(StockPurchase.created_at.desc())
                            .first()
                        )
                        if (
                            latest_purchase
                            and latest_purchase.selling_price_at_purchase is not None
                        ):
                            price_per_unit_applied = (
                                latest_purchase.selling_price_at_purchase
                            )
                        else:
                            errors_during_sale.append(
                                f"Impossible de déterminer le prix unitaire pour '{network_type.value}'. Veuillez entrer un prix manuellement."
                            )
                            continue

                if not isinstance(price_per_unit_applied, Decimal):
                    price_per_unit_applied = Decimal(str(price_per_unit_applied))

                # Calculate rounded subtotal
                subtotal = calculate_rounded_subtotal(
                    quantity=quantity, price_per_unit=price_per_unit_applied
                )

                new_sale_item = SaleItem(
                    network=network_type,
                    quantity=quantity,
                    price_per_unit_applied=price_per_unit_applied,
                    subtotal=subtotal,
                    sale=sale,  # Link to the existing sale object
                )
                sale_items_to_add.append(new_sale_item)
                total_amount_due += subtotal

                # Update stock balance for new items
                stock_item.balance -= quantity
                db.session.add(stock_item)

            if errors_during_sale:
                db.session.rollback()  # Rollback transaction
                for error in errors_during_sale:
                    flash(error, "danger")
                return render_template(
                    "home/vente_stock.html",
                    form=form,
                    sale=sale,  # Pass sale object to re-populate form on GET (or to keep context)
                    segment="stock",
                    sub_segment="vente_stock",
                )

            if not sale_items_to_add:
                db.session.rollback()  # Rollback if no items
                flash("Veuillez ajouter au moins un article à la vente.", "danger")
                return render_template(
                    "home/vente_stock.html",
                    form=form,
                    sale=sale,
                    segment="stock",
                    sub_segment="vente_stock",
                )

            # Add new sale items to the sale
            sale.sale_items.extend(sale_items_to_add)

            # 5. Update total_amount_due, cash_paid, debt_amount on the Sale
            sale.total_amount_due = total_amount_duesale
            cash_paid = form.cash_paid.data
            if cash_paid is None:
                cash_paid = Decimal("0.00")
            sale.cash_paid = cash_paid
            sale.debt_amount = total_amount_due - cash_paid
            if sale.debt_amount < 0:
                raise ValueError(
                    "L'argent donné ne peut pas dépasser le montant total dû."
                )

            db.session.add(
                sale
            )  # Re-add the sale object to session to ensure its state is managed

            db.session.commit()  # Commit the transaction
            flash("Vente modifiée avec succès!", "success")
            return redirect(
                url_for("home_blueprint.vente_stock")
            )  # Redirect to prevent re-submission

        except ValueError as e:  # Catch custom validation errors we raised
            db.session.rollback()
            flash(f"Erreur lors de la modification de la vente: {e}", "danger")
            return render_template(
                "home/vente_stock.html",
                form=form,
                sale=sale,
                segment="stock",
                sub_segment="vente_stock",
            )
        except Exception as e:
            db.session.rollback()
            flash(
                f"Erreur inattendue lors de la modification de la vente: {e}", "danger"
            )
            print(f"Error during sale edit: {e}")
            return render_template(
                "home/vente_stock.html",
                form=form,
                sale=sale,
                segment="stock",
                sub_segment="vente_stock",
            )

    return render_template(
        "home/vente_stock.html",
        form=form,
        sales=Sale.query.order_by(Sale.created_at.desc()).all(),
        segment="stock",
        sub_segment="vente_stock",
        sale_to_edit=sale,
    )


@blueprint.route("/view_sale_details/<int:sale_id>", methods=["GET"])
@login_required
def view_sale_details(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    return render_template(
        "home/sale_details.html",
        sale=sale,
        segment="stock",
        sub_segment="vente_stock",
    )


# sorties_cash route
@blueprint.route("/sorties_cash", methods=["GET"])
@login_required
def sorties_cash():
    # Fetch all cash movements for display
    all_outflows = CashOutflow.query.order_by(CashOutflow.created_at.desc()).all()
    all_inflows = CashInflow.query.order_by(CashInflow.created_at.desc()).all()

    # Calculate total cash outflow
    total_outflow = (
        sum(outflow.amount for outflow in all_outflows)
        if all_outflows
        else Decimal("0.00")
    )

    # Now, total_inflow is simply the sum of all CashInflow records
    total_inflow = (
        sum(inflow.amount for inflow in all_inflows) if all_inflows else Decimal("0.00")
    )

    # Get total cash paid directly from Sales (initial payment at sale time)
    all_sales_cash_paid = db.session.query(db.func.sum(Sale.cash_paid)).scalar()
    total_inflow = all_sales_cash_paid if all_sales_cash_paid else Decimal("0.00")

    return render_template(
        "home/sorties_cash.html",
        outflows=all_outflows,
        inflows=all_inflows,
        total_outflow=total_outflow,
        total_inflow=total_inflow,
        segment="stock",
        sub_segment="Sorties_Cash",
    )


# Enregistrer une Sortie (Cash Outflow)
@blueprint.route("/sorties_cash/enregistrer_sortie", methods=["GET", "POST"])
@login_required
def enregistrer_sortie():
    form = CashOutflowForm()

    if form.validate_on_submit():
        try:
            amount = form.amount.data
            category = CashOutflowCategory[form.category.data]
            description = form.description.data

            new_outflow = CashOutflow(
                amount=amount,
                category=category,
                description=description,
                recorded_by=current_user,
            )
            db.session.add(new_outflow)
            db.session.commit()
            flash(
                f"Sortie de {amount:,.2f} FC ({category.value}) enregistrée avec succès.",
                "success",
            )
            return redirect(
                url_for("home_blueprint.sorties_cash")
            )  # Redirect back to overview
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de l'enregistrement de la sortie: {e}", "danger")
            print(f"Error recording cash outflow: {e}")

    return render_template(
        "home/enregistrer_sortie.html",
        form=form,
        segment="stock",
        sub_segment="Sorties_Cash",
        sub_page_title="Enregistrer Sortie",
    )


# Encaisser une Dette (Debt Collection)
@blueprint.route("/sorties_cash/encaisser_dette", methods=["GET", "POST"])
@login_required
def encaisser_dette():
    form = DebtCollectionForm()

    if form.validate_on_submit():
        try:
            sale_id = form.sale_id.data
            amount_paid = form.amount_paid.data
            description = form.description.data

            sale_to_update = Sale.query.get(sale_id)

            if not sale_to_update:
                raise ValueError("Vente sélectionnée introuvable.")

            if amount_paid <= Decimal("0.00"):
                raise ValueError("Le montant payé doit être positif.")

            if amount_paid > sale_to_update.debt_amount:
                flash(
                    f"Le montant payé ({amount_paid:,.2f} FC) est supérieur à la dette restante ({sale_to_update.debt_amount:,.2f} FC). Ajustement à la dette.",
                    "warning",
                )
                amount_paid = (
                    sale_to_update.debt_amount
                )  # Cap payment at outstanding debt

            new_inflow = CashInflow(
                amount=amount_paid,
                category=CashInflowCategory.SALE_COLLECTION,
                description=description,
                recorded_by=current_user,
                sale=sale_to_update,
            )
            db.session.add(new_inflow)

            sale_to_update.cash_paid += amount_paid
            sale_to_update.debt_amount -= amount_paid
            sale_to_update.updated_at = datetime.utcnow()
            db.session.add(sale_to_update)

            db.session.commit()
            flash(
                f"Paiement de {amount_paid:,.2f} FC pour la vente #{sale_id} enregistré avec succès. Nouvelle dette: {sale_to_update.debt_amount:,.2f} FC.",
                "success",
            )
            return redirect(
                url_for("home_blueprint.sorties_cash")
            )  # Redirect back to overview
        except InvalidOperation:
            flash("Montant invalide. Veuillez entrer un nombre valide.", "danger")
            db.session.rollback()
        except ValueError as e:
            flash(f"Erreur de validation: {e}", "danger")
            db.session.rollback()
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de l'enregistrement du paiement: {e}", "danger")
            print(f"Error recording debt collection: {e}")

    return render_template(
        "home/encaisser_dette.html",
        form=form,
        segment="stock",
        sub_segment="Sorties_Cash",
        sub_page_title="Encaisser Dette",
    )


# Rapports route


# Helper function to parse date from request, or use today's date
def parse_date_param(date_str, default_date=None):
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            pass  # Fallback to default
    return default_date if default_date is not None else date.today()


@blueprint.route("/rapports", methods=["GET"])
@login_required
@superadmin_required
def rapports():
    today = date.today()
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    selected_start_date = parse_date_param(start_date_str, default_date=today)
    selected_end_date = parse_date_param(end_date_str, default_date=today)

    if selected_end_date < selected_start_date:
        selected_end_date = selected_start_date
        flash(
            "La date de fin ne peut pas être antérieure à la date de début. La date de fin a été ajustée.",
            "warning",
        )

    # Fetch all networks for iterating and initializing report_data
    networks = list(
        NetworkType.__members__.values()
    )  # Convert to list for consistent iteration

    # Initialize report data structure (per network for display)
    report_data = {}  # Start with an empty dict, will populate robustly below

    # --- Fetch Grand Totals from DailyOverallReport ---

    # Get the overall report for the start date of the period
    overall_report_start_date_obj = DailyOverallReport.query.filter_by(
        report_date=selected_start_date
    ).first()

    # Get the overall report for the end date of the period (for final values like current stock and debt)
    overall_report_end_date_obj = DailyOverallReport.query.filter_by(
        report_date=selected_end_date
    ).first()

    # Aggregate sums for purchased_stock and sold_stock over the selected range
    # Summing 'total_debts' over a range usually doesn't make sense for 'outstanding debt'
    # as debt changes. We'll use the 'total_debts' from the `overall_report_end_date_obj`.
    aggregated_overall_data = (
        db.session.query(
            func.sum(DailyOverallReport.total_purchased_stock).label("total_purchased"),
            func.sum(DailyOverallReport.total_sold_stock).label("total_sold"),
        )
        .filter(
            DailyOverallReport.report_date >= selected_start_date,
            DailyOverallReport.report_date <= selected_end_date,
        )
        .first()
    )

    # --- Construct grand_totals with robust None checks ---
    # Initialize all values to Decimal("0.00")
    grand_totals = {
        "initial_stock": Decimal("0.00"),
        "purchased_stock": Decimal("0.00"),
        "sold_stock": Decimal("0.00"),
        "final_stock": Decimal("0.00"),
        "virtual_value": Decimal("0.00"),
        "total_debts": Decimal("0.00"),
        "total_sales_from_transactions": Decimal("0.00"),
    }

    # Populate grand_totals from fetched objects, ensuring Decimal types
    if overall_report_start_date_obj:
        grand_totals["initial_stock"] = (
            overall_report_start_date_obj.total_initial_stock or Decimal("0.00")
        )

    if overall_report_end_date_obj:
        grand_totals["final_stock"] = (
            overall_report_end_date_obj.total_final_stock or Decimal("0.00")
        )
        grand_totals["virtual_value"] = (
            overall_report_end_date_obj.total_virtual_value or Decimal("0.00")
        )
        grand_totals["total_debts"] = (
            overall_report_end_date_obj.total_debts or Decimal("0.00")
        )

    if aggregated_overall_data:
        # For summed values, func.sum() returns None if no rows match, so use 'or Decimal("0.00")'
        grand_totals["purchased_stock"] = (
            aggregated_overall_data.total_purchased or Decimal("0.00")
        )
        grand_totals["sold_stock"] = aggregated_overall_data.total_sold or Decimal(
            "0.00"
        )
        grand_totals["total_sales_from_transactions"] = grand_totals[
            "sold_stock"
        ]  # This is the total quantity sold over the period

    # --- Fetch Per-Network Data from DailyStockReport ---
    for network in networks:
        network_name = network.name

        # Initialize network-specific data defaults to Decimal("0.00")
        # This acts as a fallback if any of the queries below return no data
        current_network_data = {
            "initial_stock": Decimal("0.00"),
            "purchased_stock": Decimal("0.00"),
            "sold_stock": Decimal("0.00"),
            "final_stock": Decimal("0.00"),
            "virtual_value": Decimal("0.00"),
            "debt_amount": Decimal(
                "0.00"
            ),  # DailyStockReport doesn't have debt_amount, keep it 0 or remove from this dict
            "sales_from_transactions": Decimal("0.00"),
        }

        # Get initial stock for the period from the specific network's report for selected_start_date
        network_initial_report = DailyStockReport.query.filter_by(
            network=network, report_date=selected_start_date
        ).first()
        if network_initial_report:
            current_network_data["initial_stock"] = (
                network_initial_report.initial_stock_balance or Decimal("0.00")
            )

        # Get final stock and virtual value from the specific network's report for selected_end_date
        network_final_report = DailyStockReport.query.filter_by(
            network=network, report_date=selected_end_date
        ).first()
        if network_final_report:
            current_network_data["final_stock"] = (
                network_final_report.final_stock_balance or Decimal("0.00")
            )
            current_network_data["virtual_value"] = (
                network_final_report.virtual_value or Decimal("0.00")
            )

        # Sum purchased and sold for the period for each network
        network_period_data = (
            db.session.query(
                func.sum(DailyStockReport.purchased_stock_amount).label(
                    "period_purchased"
                ),
                func.sum(DailyStockReport.sold_stock_amount).label("period_sold"),
            )
            .filter(
                DailyStockReport.network == network,
                DailyStockReport.report_date >= selected_start_date,
                DailyStockReport.report_date <= selected_end_date,
            )
            .first()
        )

        if network_period_data:
            # func.sum() results are None if no rows, so use 'or Decimal("0.00")'
            current_network_data["purchased_stock"] = (
                network_period_data.period_purchased or Decimal("0.00")
            )
            current_network_data["sold_stock"] = (
                network_period_data.period_sold or Decimal("0.00")
            )
            current_network_data["sales_from_transactions"] = current_network_data[
                "sold_stock"
            ]

        # Assign the robustly populated current_network_data to report_data
        report_data[network_name] = current_network_data

    # --- Stock Vendus vs. Sales Total Reconciliation ---
    # This calculation should now be safe as all grand_totals values are guaranteed Decimal.
    total_derived_sold_from_balance = (
        grand_totals["initial_stock"]
        + grand_totals["purchased_stock"]
        - grand_totals["final_stock"]
    )

    imbalance_message = None
    tolerance = Decimal("0.01")

    # Ensure all values in comparison are Decimal
    if (
        abs(
            total_derived_sold_from_balance
            - grand_totals["total_sales_from_transactions"]
        )
        > tolerance
    ):
        imbalance_message = (
            f"Déséquilibre détecté : Le 'Stock Vendus' calculé du rapport ({total_derived_sold_from_balance:,.2f} FC) "
            f"ne correspond pas au total des ventes enregistrées ({grand_totals['total_sales_from_transactions']:,.2f} FC). "
            f"Cela peut indiquer un achat non enregistré, une vente non enregistrée ou une erreur de saisie."
        )

    return render_template(
        "home/rapports.html",
        report_data=report_data,
        networks=networks,
        grand_totals=grand_totals,
        selected_start_date=selected_start_date.strftime("%Y-%m-%d"),
        selected_end_date=selected_end_date.strftime("%Y-%m-%d"),
        segment="rapports",
        page_title="Rapport Stock & Ventes",
        imbalance_message=imbalance_message,
    )

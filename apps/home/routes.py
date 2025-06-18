from apps.home import blueprint
from flask import render_template, request, flash, redirect, url_for, abort, current_app
from flask_login import login_required, current_user
from jinja2 import TemplateNotFound
from apps.decorators import superadmin_required, vendeur_required
from apps import db
from decimal import Decimal
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
)

from apps.home.forms import (
    StockerForm,
    UserEditForm,
    ClientForm,
    ClientEditForm,
    StockPurchaseForm,
    SaleForm,
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
    form = StockPurchaseForm()

    if form.validate_on_submit():
        try:
            network_enum_value = form.network.data
            network_enum = NetworkType(network_enum_value)
            amount_purchased = form.amount_purchased.data
            selling_price_to_record_in_stock = None

            # Determine selling_price_to_record_in_stock based on user's choice
            if form.selling_price_choice.data == "custom":
                selling_price_to_record_in_stock = form.custom_selling_price.data
                if selling_price_to_record_in_stock is None:
                    flash("Prix de vente personnalisé est requis.", "danger")
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
            elif form.selling_price_choice.data in ["27.5", "28.0"]:
                selling_price_to_record_in_stock = Decimal(
                    form.selling_price_choice.data
                )
            else:
                # For now, let's make it clear that a price MUST be chosen.
                flash("Veuillez sélectionner ou entrer un prix de vente.", "danger")
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

            # Retrieve the Stock item for the chosen network
            stock_item = Stock.query.filter_by(network=network_enum).first()

            if stock_item:
                # Update the stock balance
                stock_item.balance += amount_purchased
                # CRUCIAL: Update the selling_price_per_unit in the Stock table
                stock_item.selling_price_per_unit = selling_price_to_record_in_stock
            else:
                # If no stock item exists for this network, create a new one
                stock_item = Stock(
                    network=network_enum,
                    balance=amount_purchased,
                    selling_price_per_unit=selling_price_to_record_in_stock,
                    reduction_rate=Decimal(
                        "0.00"
                    ),  # Initialize reduction_rate if new stock
                )
                db.session.add(stock_item)

            # Flush the session to get the stock_item.id if it's new
            db.session.flush()

            new_purchase = StockPurchase(
                stock_item_id=stock_item.id,
                network=network_enum,
                amount_purchased=amount_purchased,
                selling_price_at_purchase=selling_price_to_record_in_stock,
                purchased_by=current_user,
            )
            db.session.add(new_purchase)
            db.session.commit()
            flash("Achat de stock enregistré avec succès!", "success")
            return redirect(url_for("home_blueprint.Achat_stock"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error recording stock purchase: {e}")
            flash(
                f"Une erreur est survenue lors de l'enregistrement de l'achat: {e}",
                "danger",
            )

    # For GET request or if form validation fails
    stock_purchases = StockPurchase.query.order_by(
        StockPurchase.created_at.desc()
    ).all()
    return render_template(
        "home/achat_stock.html",
        segment="stock",
        sub_segment="Achat_stock",
        stock_purchases=stock_purchases,
        form=form,
    )


@blueprint.route("/vente_stock", methods=["GET", "POST"])
@login_required
@superadmin_required
@vendeur_required
def vente_stock():
    form = SaleForm()

    # IMPORTANT FIX: Set choices for existing_client_id field HERE
    # This ensures it runs within the application context.

    clients = Client.query.filter_by(is_active=True).order_by(Client.name).all()
    client_choices = [("", "Sélectionnez un client existant")]
    client_choices.extend([(str(client.id), client.name) for client in clients])
    form.existing_client_id.choices = client_choices

    # Populate sale_items FieldList with initial empty forms for GET requests
    if request.method == "GET" and not form.sale_items:
        # Pre-populate 3 empty SaleItemForms, for example
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
                    # No need to re-set choices as the form object already has them
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
                # Append errors from subform fields
                for field_name, field_errors in item_data.form.errors.items():
                    for error in field_errors:
                        errors_during_sale.append(
                            f"Erreur dans l'article {item_data.id}: {item_data.form[field_name].label.text}: {error}"
                        )
                continue  # Skip this item if its subform is invalid

            network_type = NetworkType[item_data.form.network.data]
            quantity = item_data.form.quantity.data
            price_per_unit_applied = item_data.form.price_per_unit_applied.data
            reduction_rate_applied = item_data.form.reduction_rate_applied.data

            # Fetch stock to ensure it exists and to calculate subtotal
            stock_item = Stock.query.filter_by(network=network_type).first()

            if not stock_item:
                errors_during_sale.append(
                    f"Réseau '{network_type.value}' non trouvé en stock."
                )
                continue

            if quantity > stock_item.balance:
                errors_during_sale.append(
                    f"Quantité insuffisante pour {network_type.value}. Disponible: {stock_item.balance}, Demandé: {quantity}."
                )
                continue

            # Calculate subtotal using the entered values
            if reduction_rate_applied is None:
                reduction_rate_applied = Decimal("0.00")
            if price_per_unit_applied is None:
                price_per_unit_applied = Decimal("27.5")
            subtotal = (
                quantity * price_per_unit_applied * (1 - (reduction_rate_applied / 100))
            )

            # Create SaleItem object
            new_sale_item = SaleItem(
                network=network_type,
                quantity=quantity,
                price_per_unit_applied=price_per_unit_applied,
                reduction_rate_applied=reduction_rate_applied,
                subtotal=subtotal,
            )
            sale_items_to_add.append(new_sale_item)
            total_amount_due += subtotal

            # Update stock balance immediately
            stock_item.balance -= quantity
            print(
                f"Updated stock for {network_type.value}: New balance is {stock_item.balance}"
            )
            db.session.add(stock_item)

        if errors_during_sale:
            # If there are errors, revert stock changes for items processed so far
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

        # Create the main Sale object
        cash_paid = form.cash_paid.data
        if cash_paid is None:
            cash_paid = Decimal("0.00")
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

        # Add sale items to the new sale
        new_sale.sale_items.extend(sale_items_to_add)
        print(
            f"Prepared sale with {len(sale_items_to_add)} items, total amount due: {total_amount_due}"
        )
        try:
            db.session.add(new_sale)
            db.session.commit()
            flash("Vente enregistrée avec succès!", "success")
            return redirect(
                url_for("home_blueprint.vente_stock")
            )  # Redirect to prevent re-submission
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de l'enregistrement de la vente: {e}", "danger")
            # Log the error for debugging
            print(f"Error saving sale: {e}")
        print(
            f"Sale recorded with {len(sale_items_to_add)} items, total amount due: {total_amount_due}"
        )
    else:
        # This block executes if form.validate_on_submit() is False
        print("Form validation failed. Errors:")  # This print *should* show up
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {field}: {error}", "error")
                print(f"Error in {field}: {error}")  # This print *should* show up

        # Also check errors on nested FieldList forms
        for i, entry in enumerate(form.sale_items.entries):
            if entry.form.errors:
                print(f"Errors in Sale Item {i}:")
                for field_name, field_errors in entry.form.errors.items():
                    for error in field_errors:
                        flash(
                            f"Error in Sale Item {i} - {field_name}: {error}", "danger"
                        )
                        print(f"Error in Sale Item {i} - {field_name}: {error}")
    # Fetch existing sales for the table
    sales = Sale.query.order_by(Sale.created_at.desc()).all()

    return render_template(
        "home/vente_stock.html",
        form=form,
        sales=sales,
        segment="stock",
        sub_segment="vente_stock",
    )


# Route to handle updating cash paid (for editing debt) - This needs to be implemented separately
@blueprint.route("/update-sale-cash/<int:sale_id>", methods=["POST"])
@login_required
def update_sale_cash(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    # Ensure form data is handled with proper validation or try-except for Decimal conversion
    try:
        new_cash = Decimal(request.form.get("new_cash", "0.00"))
    except InvalidOperation:  # From decimal module
        flash("Montant d'argent donné invalide.", "danger")
        return redirect(url_for("home_blueprint.vente_stock"))

    if new_cash < 0:
        flash("L'argent donné ne peut pas être négatif.", "danger")
        return redirect(url_for("home_blueprint.vente_stock"))

    # Calculate new debt
    new_debt = sale.total_amount_due - new_cash

    if new_debt < 0:
        flash("L'argent donné ne peut pas dépasser le montant total dû.", "danger")
        return redirect(url_for("home_blueprint.vente_stock"))

    sale.cash_paid = new_cash
    sale.debt_amount = new_debt
    sale.updated_at = datetime.utcnow()

    try:
        db.session.commit()
        flash("Argent donné mis à jour avec succès!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de la mise à jour: {e}", "danger")
        print(f"Error updating cash: {e}")

    # For AJAX requests, it's common to return a JSON response
    # instead of redirecting directly if the update is meant to be seamless.
    # However, for simplicity and page reload, a redirect is fine.
    # If you want to stay on the page and update dynamically, return jsonify({"success": True, "new_cash": str(new_cash), "new_debt": str(new_debt)})
    return redirect(url_for("home_blueprint.vente_stock"))

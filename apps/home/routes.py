from apps.home import blueprint
from flask import render_template, request, flash, redirect, url_for, abort, current_app
from flask_login import login_required, current_user
import sqlalchemy as sa
from sqlalchemy.sql import func, cast
from sqlalchemy.types import Date
from jinja2 import TemplateNotFound
from apps.decorators import superadmin_required, vendeur_required
from apps.home.utils import (
    custom_round_up,
    parse_date_param,
    get_daily_report_data,
    get_local_timezone_datetime_info,
    APP_TIMEZONE,
)

from apps import db
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone, date
import pytz
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
    EditProfileForm,
)


# Define the timezone for the application
APP_TIMEZONE = pytz.timezone("Africa/Lubumbashi")


@blueprint.route("/index")
@login_required
def index():
    # Use the new utility function to get timezone-aware date/time info
    local_now, today_local_date, start_of_local_day_utc, end_of_local_day_utc = (
        get_local_timezone_datetime_info()
    )

    # --- 1. Total Stock for each network (Card stats) ---
    current_stocks = Stock.query.all()
    total_stocks_data = {stock.network.value: stock.balance for stock in current_stocks}

    # --- 2. Sales Over Time (Chart 1 - Sales Value) ---
    sales_data_week = {}
    # Iterate through local dates, but filter by UTC time range
    for i in range(6, -1, -1):
        target_local_date = today_local_date - timedelta(days=i)
        # Recalculate UTC bounds for each target_local_date using the APP_TIMEZONE
        start_of_target_day_utc = APP_TIMEZONE.localize(
            datetime(
                target_local_date.year,
                target_local_date.month,
                target_local_date.day,
                0,
                0,
                0,
            )
        ).astimezone(pytz.utc)
        end_of_target_day_utc = APP_TIMEZONE.localize(
            datetime(
                target_local_date.year,
                target_local_date.month,
                target_local_date.day,
                23,
                59,
                59,
                999999,
            )
        ).astimezone(pytz.utc)

        # Query using the UTC datetime range
        daily_sales = (
            db.session.query(func.sum(Sale.total_amount_due))
            .filter(
                Sale.created_at >= start_of_target_day_utc,
                Sale.created_at <= end_of_target_day_utc,
            )
            .scalar()
        )
        sales_data_week[target_local_date.strftime("%a")] = (
            float(daily_sales) if daily_sales else 0.00
        )

    # --- 3. Sales by Network (Chart 2 - Total Orders/Performance) ---
    sales_by_network = {}
    for network in NetworkType:
        network_sales = (
            db.session.query(func.sum(SaleItem.subtotal))
            .filter(
                SaleItem.network == network,
                # Filter by UTC datetime range for the current local day
                SaleItem.created_at >= start_of_local_day_utc,
                SaleItem.created_at <= end_of_local_day_utc,
            )
            .scalar()
        )
        sales_by_network[network.value] = (
            float(network_sales) if network_sales else 0.00
        )

    # --- 4. Key Performance Indicators (Card Stats) ---
    # Total Sales (Today - based on local timezone's definition of "today")
    total_sales_today = (
        db.session.query(func.sum(Sale.total_amount_due))
        .filter(
            Sale.created_at >= start_of_local_day_utc,
            Sale.created_at <= end_of_local_day_utc,
        )
        .scalar()
    )
    total_sales_today = float(total_sales_today) if total_sales_today else 0.00

    # Total Debt (Currently outstanding) - This query is fine as it's not date-specific
    total_debt = (
        db.session.query(func.sum(Sale.debt_amount))
        .filter(
            Sale.debt_amount > 0,
            # If you want to show total debt *as of end of today's local time*, uncomment below:
            # Sale.created_at <= end_of_local_day_utc,
        )
        .scalar()
    )
    total_debt = float(total_debt) if total_debt else 0.00

    # Total Cash Inflow (Today, from sales collection and other inflows)
    total_cash_inflow_sales = (
        db.session.query(func.sum(Sale.cash_paid))
        .filter(
            Sale.created_at >= start_of_local_day_utc,
            Sale.created_at <= end_of_local_day_utc,
        )
        .scalar()
    )
    total_cash_inflow_other = (
        db.session.query(func.sum(CashInflow.amount))
        .filter(
            CashInflow.created_at >= start_of_local_day_utc,
            CashInflow.created_at <= end_of_local_day_utc,
        )
        .scalar()
    )

    total_cash_inflow_today = (
        total_cash_inflow_sales if total_cash_inflow_sales else Decimal("0.00")
    ) + (total_cash_inflow_other if total_cash_inflow_other else Decimal("0.00"))
    total_cash_inflow_today = float(total_cash_inflow_today)

    # Total Cash Outflow (Today)
    total_cash_outflow_today = (
        db.session.query(func.sum(CashOutflow.amount))
        .filter(
            CashOutflow.created_at >= start_of_local_day_utc,
            CashOutflow.created_at <= end_of_local_day_utc,
        )
        .scalar()
    )
    total_cash_outflow_today = (
        float(total_cash_outflow_today) if total_cash_outflow_today else 0.00
    )

    # --- 5. Recent Sales History (Table) ---
    recent_sales = (
        Sale.query.options(
            db.joinedload(Sale.vendeur),
            db.joinedload(Sale.client),
            db.joinedload(Sale.sale_items),
        )
        .order_by(Sale.created_at.desc())
        .limit(5)
        .all()
    )

    # --- 6. Daily Stock Report and Overall Report (Summary Tables) ---
    # Query for yesterday's reports for display on the index,
    # as they are typically generated for the completed previous day.
    yesterday_local_date = today_local_date - timedelta(days=1)

    daily_stock_reports = DailyStockReport.query.filter_by(
        report_date=yesterday_local_date
    ).all()
    daily_overall_report = DailyOverallReport.query.filter_by(
        report_date=yesterday_local_date
    ).first()

    # Optional: If you want to display 'No Report Yet' for today if the cron hasn't run
    # You could check if daily_overall_report is None and provide a message to the template.

    return render_template(
        "home/index.html",
        segment="index",
        total_stocks_data=total_stocks_data,
        sales_data_week=sales_data_week,
        sales_by_network=sales_by_network,
        total_sales_today=total_sales_today,
        total_debt=total_debt,
        total_cash_inflow_today=total_cash_inflow_today,
        total_cash_outflow_today=total_cash_outflow_today,
        recent_sales=recent_sales,
        daily_stock_reports=daily_stock_reports,
        daily_overall_report=daily_overall_report,
        NetworkType=NetworkType,
    )


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
        user_edit_form.is_active.data = user.is_activeH

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

            network_type_string_from_form = form.network.data
            try:
                network_enum = NetworkType(network_type_string_from_form.lower())
            except ValueError:
                flash(
                    f"Le type de réseau '{network_type_string_from_form}' n'est pas valide.",
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
@blueprint.route("/rapports", methods=["GET"])
@login_required
@superadmin_required
def rapports():
    page_title = "Rapport Stock & Ventes"

    # Use the new utility function for current local date and UTC bounds
    _, today_local_date, start_of_local_day_utc, end_of_local_day_utc = (
        get_local_timezone_datetime_info()
    )

    # Determine default date range for reports
    default_start_date = today_local_date - timedelta(days=1)
    default_end_date = today_local_date - timedelta(days=1)

    test_report_exists = DailyOverallReport.query.first()
    if not test_report_exists:
        current_app.logger.info(
            "No historical stock reports found. Defaulting report range to today (live data)."
        )
        default_start_date = today_local_date
        default_end_date = today_local_date

    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    selected_start_date = parse_date_param(
        start_date_str, default_date=default_start_date
    )
    selected_end_date = parse_date_param(end_date_str, default_date=default_end_date)

    if selected_end_date < selected_start_date:
        flash(
            "La date de fin ne peut pas être antérieure à la date de début. La date de fin a été ajustée.",
            "warning",
        )
        selected_end_date = selected_start_date

    current_app.logger.debug(
        f"Report requested for: Start={selected_start_date}, End={selected_end_date}"
    )

    networks = list(NetworkType.__members__.values())

    report_data = {
        network.name: {
            "initial_stock": Decimal("0.00"),
            "purchased_stock": Decimal("0.00"),
            "sold_stock": Decimal("0.00"),
            "final_stock": Decimal("0.00"),
            "virtual_value": Decimal("0.00"),
            "debt_amount": Decimal("0.00"),
            "sales_from_transactions_value": Decimal("0.00"),
            "network": network,
        }
        for network in networks
    }

    grand_totals = {
        "initial_stock": Decimal("0.00"),
        "purchased_stock": Decimal("0.00"),
        "sold_stock": Decimal("0.00"),
        "final_stock": Decimal("0.00"),
        "virtual_value": Decimal("0.00"),
        "total_debts": Decimal("0.00"),
    }

    overall_report_for_display = None

    if (
        selected_start_date == today_local_date
        and selected_end_date == today_local_date
    ):
        current_app.logger.info("Fetching live report data for today.")
        # Pass the calculated UTC ranges from the utility function
        calculated_data, total_sales_val, total_live_debts = get_daily_report_data(
            current_app,
            today_local_date,  # target_date is today's local date
            start_of_utc_range=start_of_local_day_utc,
            end_of_utc_range=end_of_local_day_utc,
        )

        for network_name, data in calculated_data.items():
            report_data[network_name].update(
                {
                    "initial_stock": data["initial_stock"],
                    "purchased_stock": data["purchased_stock"],
                    "sold_stock": data["sold_stock_quantity"],
                    "final_stock": data["final_stock"],
                    "virtual_value": data["virtual_value"],
                    "sales_from_transactions_value": data["sold_stock_value"],
                }
            )

            grand_totals["initial_stock"] += data["initial_stock"]
            grand_totals["purchased_stock"] += data["purchased_stock"]
            grand_totals["sold_stock"] += data["sold_stock_quantity"]
            grand_totals["final_stock"] += data["final_stock"]
            grand_totals["virtual_value"] += data["virtual_value"]

        # total_live_debts is now returned directly from get_daily_report_data
        grand_totals["total_debts"] = (
            total_live_debts if total_live_debts is not None else Decimal("0.00")
        )
        current_app.logger.info(
            f"++++++++++++++++ This is the total live debts {total_live_debts} ++++++++++++++++++++++++++++++++++"
        )

        grand_totals["total_calculated_sold_stock"] = (
            grand_totals["initial_stock"]
            + grand_totals["purchased_stock"]
            - grand_totals["final_stock"]
        )

    elif selected_start_date == selected_end_date:
        current_app.logger.info(
            f"Fetching historical report data for {selected_start_date}."
        )

        overall_report_for_display = DailyOverallReport.query.filter_by(
            report_date=selected_start_date
        ).first()

        if overall_report_for_display:
            grand_totals["initial_stock"] = (
                overall_report_for_display.total_initial_stock
            )
            grand_totals["purchased_stock"] = (
                overall_report_for_display.total_purchased_stock
            )
            grand_totals["sold_stock"] = overall_report_for_display.total_sold_stock
            grand_totals["final_stock"] = overall_report_for_display.total_final_stock
            grand_totals["virtual_value"] = (
                overall_report_for_display.total_virtual_value
            )
            grand_totals["total_debts"] = overall_report_for_display.total_debts

            grand_totals["total_calculated_sold_stock"] = (
                overall_report_for_display.total_initial_stock
                + overall_report_for_display.total_purchased_stock
                - overall_report_for_display.total_final_stock
            )

            daily_network_reports = DailyStockReport.query.filter_by(
                report_date=selected_start_date
            ).all()
            for r in daily_network_reports:
                if r.network.name in report_data:
                    report_data[r.network.name].update(
                        {
                            "initial_stock": r.initial_stock_balance,
                            "purchased_stock": r.purchased_stock_amount,
                            "sold_stock": r.sold_stock_amount,
                            "final_stock": r.final_stock_balance,
                            "virtual_value": r.virtual_value,
                        }
                    )
        else:
            flash(
                f"Aucun rapport disponible pour la date sélectionnée : {selected_start_date.strftime('%Y-%m-%d')}.",
                "info",
            )
            current_app.logger.warning(
                f"No historical overall report found for {selected_start_date}"
            )

    else:
        current_app.logger.info(
            f"Aggregating historical report data from {selected_start_date} to {selected_end_date}."
        )

        range_overall_reports = DailyOverallReport.query.filter(
            DailyOverallReport.report_date >= selected_start_date,
            DailyOverallReport.report_date <= selected_end_date,
        ).all()

        if range_overall_reports:
            first_day_overall_report = DailyOverallReport.query.filter_by(
                report_date=selected_start_date
            ).first()
            last_day_overall_report = DailyOverallReport.query.filter_by(
                report_date=selected_end_date
            ).first()

            if first_day_overall_report:
                grand_totals["initial_stock"] = (
                    first_day_overall_report.total_initial_stock
                )
            else:
                grand_totals["initial_stock"] = Decimal("0.00")

            for r in range_overall_reports:
                grand_totals["purchased_stock"] += r.total_purchased_stock
                grand_totals["sold_stock"] += r.total_sold_stock

            if last_day_overall_report:
                grand_totals["final_stock"] = last_day_overall_report.total_final_stock
                grand_totals["virtual_value"] = (
                    last_day_overall_report.total_virtual_value
                )
                grand_totals["total_debts"] = last_day_overall_report.total_debts
            else:
                grand_totals["final_stock"] = Decimal("0.00")
                grand_totals["virtual_value"] = Decimal("0.00")
                grand_totals["total_debts"] = Decimal("0.00")

            grand_totals["total_calculated_sold_stock"] = (
                grand_totals["initial_stock"]
                + grand_totals["purchased_stock"]
                - grand_totals["final_stock"]
            )

            for network in networks:
                network_range_reports = DailyStockReport.query.filter(
                    DailyStockReport.network == network,
                    DailyStockReport.report_date >= selected_start_date,
                    DailyStockReport.report_date <= selected_end_date,
                ).all()

                network_initial_stock_for_range = Decimal("0.00")
                network_purchased_stock_for_range = Decimal("0.00")
                network_sold_stock_for_range = Decimal("0.00")
                network_final_stock_for_range = Decimal("0.00")
                network_virtual_value_for_range = Decimal("0.00")

                if network_range_reports:
                    first_network_report_in_range = DailyStockReport.query.filter(
                        DailyStockReport.network == network,
                        DailyStockReport.report_date == selected_start_date,
                    ).first()
                    if first_network_report_in_range:
                        network_initial_stock_for_range = (
                            first_network_report_in_range.initial_stock_balance
                        )

                    for r in network_range_reports:
                        network_purchased_stock_for_range += r.purchased_stock_amount
                        network_sold_stock_for_range += r.sold_stock_amount

                    last_network_report_in_range = DailyStockReport.query.filter(
                        DailyStockReport.network == network,
                        DailyStockReport.report_date == selected_end_date,
                    ).first()
                    if last_network_report_in_range:
                        network_final_stock_for_range = (
                            last_network_report_in_range.final_stock_balance
                        )
                        network_virtual_value_for_range = (
                            last_network_report_in_range.virtual_value
                        )

                report_data[network.name].update(
                    {
                        "initial_stock": network_initial_stock_for_range,
                        "purchased_stock": network_purchased_stock_for_range,
                        "sold_stock": network_sold_stock_for_range,
                        "final_stock": network_final_stock_for_range,
                        "virtual_value": network_virtual_value_for_range,
                    }
                )

        else:
            flash(
                f"Aucun rapport disponible pour la plage de dates sélectionnée.", "info"
            )
            current_app.logger.warning(
                f"No historical reports found for range {selected_start_date} to {selected_end_date}"
            )

    return render_template(
        "home/rapports.html",
        page_title=page_title,
        networks=networks,
        report_data=report_data,
        grand_totals=grand_totals,
        selected_start_date=selected_start_date.strftime("%Y-%m-%d"),
        selected_end_date=selected_end_date.strftime("%Y-%m-%d"),
    )


@blueprint.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = EditProfileForm(
        original_username=current_user.username, original_email=current_user.email
    )

    if form.validate_on_submit():
        # Handle form submission for username, email, phone
        if current_user.username != form.username.data:
            current_user.username = form.username.data
        if current_user.email != form.email.data:
            current_user.email = form.email.data
        if current_user.phone != form.phone.data:
            current_user.phone = form.phone.data

        # Handle password change (your existing logic with translated flashes)
        if form.current_password.data or form.new_password.data:
            if not form.current_password.data:
                flash(
                    "Veuillez entrer votre mot de passe actuel pour changer le mot de passe.",
                    "danger",
                )
                return redirect(url_for("home_blueprint.profile"))
            if not current_user.check_password(form.current_password.data):
                flash("Mot de passe actuel incorrect.", "danger")
                return redirect(url_for("home_blueprint.profile"))
            if not form.new_password.data:
                flash("Veuillez entrer un nouveau mot de passe.", "danger")
                return redirect(url_for("home_blueprint.profile"))
            if form.new_password.data != form.confirm_new_password.data:
                flash("Les nouveaux mots de passe ne correspondent pas.", "danger")
                return redirect(url_for("home_blueprint.profile"))

            current_user.set_password(form.new_password.data)
            flash("Votre mot de passe a été mis à jour !", "success")

        try:
            db.session.commit()
            flash("Votre profil a été mis à jour !", "success")
            return redirect(url_for("home_blueprint.profile"))
        except Exception as e:
            db.session.rollback()
            flash(f"Une erreur est survenue : {e}", "danger")

    elif request.method == "GET":
        # Pre-populate form fields when page is loaded (GET request)
        form.username.data = current_user.username
        form.email.data = current_user.email
        form.phone.data = current_user.phone
        if hasattr(current_user, "about_me"):  # Pre-populate about_me if it exists
            form.about_me.data = current_user.about_me
        if hasattr(form, "role") and current_user.role:
            form.role.data = (
                current_user.role.name
            )  # Pre-select the current role using its name (e.g., 'SUPERADMIN')
        if hasattr(form, "is_active"):
            form.is_active.data = current_user.is_active

    # Fetch additional data for the profile page
    num_clients_created = (
        len(current_user.clients)
        if hasattr(current_user, "clients") and current_user.clients is not None
        else 0
    )
    num_sales_made = (
        len(current_user.sales)
        if hasattr(current_user, "sales") and current_user.sales is not None
        else 0
    )
    num_stock_purchases = (
        current_user.stock_purchases_made.count()
        if hasattr(current_user, "stock_purchases_made")
        else 0
    )

    return render_template(
        "home/profile.html",
        segment="profile",
        form=form,
        num_clients_created=num_clients_created,
        num_sales_made=num_sales_made,
        num_stock_purchases=num_stock_purchases,
    )

from apps.main import bp
from flask import render_template, request, flash, redirect, url_for, abort, current_app
from flask_login import login_required, current_user
import sqlalchemy as sa
from sqlalchemy import func
from jinja2 import TemplateNotFound
from apps.decorators import superadmin_required, vendeur_required
from apps.main.utils import (
    custom_round_up,
    get_paginated_results,
    get_daily_report_data,
    get_local_timezone_datetime_info,
    APP_TIMEZONE,
    get_date_context,
    get_stock_purchase_history_query,
    get_sales_history_query,
    update_daily_reports,

)

from apps import db
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone, date
import pytz
from apps.models import (
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
    CashInflowCategory,
    DailyOverallReport,
    DailyStockReport,
)

from apps.main.forms import (
    ChangePasswordForm,
    StockerForm,
    UpdateProfileForm,
    UserEditForm,
    ClientForm,
    ClientEditForm,
    StockPurchaseForm,
    SaleForm,
    CashOutflowForm,
    DebtCollectionForm,
    EditProfileForm,
    DeleteConfirmForm,
)


# Define the timezone for the application
APP_TIMEZONE = pytz.timezone("Africa/Lubumbashi")


@bp.route("/health")
def health():
    return {"status": "ok"}, 200


@bp.route("/")
@bp.route("/index")
@login_required
def index():
    # Use the new utility function to get timezone-aware date/time info
    local_now, today_local_date, start_of_local_day_utc, end_of_local_day_utc = (
        get_local_timezone_datetime_info()
    )

    # --- 1. Total Stock for each network (Card stats) ---
    current_stocks = Stock.query.all()
    total_stocks_data = {
        stock.network.value: stock.balance for stock in current_stocks}

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
        "main/index.html",
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


@bp.route("/<template>")
@login_required
def route_template(template):
    try:
        if not template.endswith(".html"):
            template += ".html"

        segment = get_segment(request)
        return render_template("main/" + template, segment=segment)

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
@bp.route("/admin/stocker", methods=["GET", "POST"])
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
        # Check if username already exists
        existing_user = User.query.filter(
            User.username == stocker_form.username.data
        ).first()

        # Si email est fourni, on vérifie s'il est déjà utilisé
        if stocker_form.email.data:
            existing_email = User.query.filter(
                User.email == stocker_form.email.data
            ).first()
        else:
            existing_email = None

        if existing_user or existing_email:
            flash("Nom d'utilisateur ou email déjà utilisé.", "danger")
        else:
            new_user = User(
                username=stocker_form.username.data,
                phone=stocker_form.phone.data,
                email=stocker_form.email.data or None,  # email optionnel
                role=RoleType(stocker_form.role.data),
                created_by=current_user.id,
            )
            new_user.set_password(stocker_form.password.data)
            db.session.add(new_user)
            db.session.commit()
            flash("Utilisateur créé avec succès!", "success")
            return redirect(url_for("main_bp.stocker_management"))


    users = User.query.all()
    return render_template(
        "main/user.html",
        users=users,
        stocker_form=stocker_form,
        user_edit_form=user_edit_form,
        segment="admin",
        sub_segment="stocker",
    )


@bp.route("/admin/user/edit/<int:user_id>", methods=["GET", "POST"])
@login_required
@superadmin_required
def user_edit(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("Utilisateur non trouvé.", "danger")
        return redirect(url_for("main_bp.stocker_management"))

    user_edit_form = UserEditForm()
    stocker_form = StockerForm()
    
    if user_edit_form.validate_on_submit():
        # Check if username already exists for another user
        existing_user_by_username = User.query.filter(
            User.username == user_edit_form.username.data, User.id != user_id
        ).first()

        # Email check only if email provided
        if user_edit_form.email.data:
            existing_user_by_email = User.query.filter(
                User.email == user_edit_form.email.data, User.id != user_id
            ).first()
        else:
            existing_user_by_email = None

        if existing_user_by_username:
            flash("Nom d'utilisateur déjà utilisé", "danger")
        elif existing_user_by_email:
            flash("Email déjà utilisé ", "danger")
        else:
            user.username = user_edit_form.username.data
            user.phone = user_edit_form.phone.data
            user.email = user_edit_form.email.data or None
            user.role = RoleType(user_edit_form.role.data)
            user.is_active = user_edit_form.is_active.data
            db.session.commit()
            flash("Utilisateur mis à jour avec succès!", "success")
            return redirect(url_for("main_bp.stocker_management"))


        

    elif request.method == "GET":
        # Pre-populate form with existing user data on GET request
        user_edit_form.username.data = user.username
        user_edit_form.email.data = user.email
        user_edit_form.role.data = user.role.value
        user_edit_form.is_active.data = user.is_active

    users = User.query.all()
    return render_template(
        "main/user.html",
        users=users,
        stocker_form=stocker_form,
        user_edit_form=user_edit_form,
        segment="admin",
        sub_segment="stocker",
    )


@bp.route("/admin/user/toggle_active/<int:user_id>", methods=["POST"])
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
                flash(        f"Utilisateur '{user.username}' activé avec succès!", "success")
            else:
                flash(        f"Utilisateur '{user.username}' désactivé avec succès!", "success"
                )
    return redirect(url_for("main_bp.stocker_management"))


# Client Management
@bp.route("/admin/clients", methods=["GET", "POST"])
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

        existing_client = Client.query.filter_by(
            name=client_form.name.data).first()

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
                vendeur=current_user,
            )
            db.session.add(new_client)
            db.session.commit()
            flash("Client créé avec succès!", "success")
            return redirect(url_for("main_bp.client_management"))

    # Query clients
    if current_user.role == RoleType.SUPERADMIN:
        clients = Client.query.all()
    else:
        clients = Client.query.filter_by(vendeur_id=current_user.id).all()

    return render_template(
        "main/clients.html",
        clients=clients,
        client_form=client_form,
        client_edit_form=client_edit_form,
        segment="admin",
        sub_segment="clients",
    )


@bp.route("/admin/clients/edit/<int:client_id>", methods=["POST"])
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
        return redirect(url_for("main_bp.client_management"))

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

        db.session.commit()
        flash("Client mis à jour avec succès!", "success")
        return redirect(url_for("main_bp.client_management"))
    else:
        # If validation fails, repopulate the form with existing data and show errors
        # This is where the modal JS will pick up errors and reopen the modal
        flash("Erreur lors de la mise à jour du client. Veuillez vérifier les champs.",
            "danger",
        )
        # Pre-populate form for re-rendering if validation fails (important for modal)
        # This part is handled by the data attributes in the JS when the modal is re-opened.
        # However, if you redirect with errors, you might want to flash them more specifically.
    return redirect(url_for("main_bp.client_management"))


@bp.route("/admin/clients/toggle-active/<int:client_id>", methods=["POST"])
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
        return redirect(url_for("main_bp.client_management"))

    client.is_active = not client.is_active
    db.session.commit()
    status_message = "activé" if client.is_active else "désactivé"
    flash(f"Client {client.name} {status_message} avec succès!", "success")
    return redirect(url_for("main_bp.client_management"))


@bp.route("/achat_stock", methods=["GET", "POST"])
@login_required
@superadmin_required
def achat_stock():
    form = StockPurchaseForm()

    # --- 1. HANDLE POST (Processing the Purchase) ---
    if form.validate_on_submit():
        try:
            # A. Extract Network
            network_type_string_from_form = form.network.data
            try:
                # Assuming NetworkType is your Enum
                network_enum = NetworkType(
                    network_type_string_from_form.lower())
            except ValueError:
                raise ValueError(
                    f"Le type de réseau '{network_type_string_from_form}' n'est pas valide.")

            # B. Extract Amounts
            amount_purchased = form.amount_purchased.data

            # C. Determine Buying Price
            buying_price_to_record = None
            if form.buying_price_choice.data == "custom":
                buying_price_to_record = form.custom_buying_price.data
            elif form.buying_price_choice.data:
                buying_price_to_record = Decimal(form.buying_price_choice.data)

            # D. Determine Selling Price
            selling_price_to_record = None
            if form.intended_selling_price_choice.data == "custom":
                selling_price_to_record = form.custom_intended_selling_price.data
            elif form.intended_selling_price_choice.data:
                selling_price_to_record = Decimal(
                    form.intended_selling_price_choice.data)

            # E. Validate Prices
            if buying_price_to_record is None or selling_price_to_record is None:
                raise ValueError(
                    "Veuillez sélectionner ou entrer un prix d'achat et un prix de vente.")

            # F. Database Operations
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

            # Flush to get IDs if needed, though commit handles it
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
            # Redirect to Clear the POST request
            return redirect(url_for("main_bp.achat_stock"))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), "danger")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error recording stock purchase: {e}")
            flash("Une erreur système est survenue lors de l'enregistrement.", "danger")

    elif form.errors:
        # This helps debug if Validation is failing silently
        print("Form Errors:", form.errors)
        flash("Veuillez corriger les erreurs dans le formulaire.", "danger")

    # --- 2. HANDLE GET (Data Fetching & Pagination) ---

    # Use helper to get query and context
    base_purchases_query, ctx = get_stock_purchase_history_query(
        date_filter=True)
    selected_date_str = ctx.get('date_str')

    # Paginate results
    stock_purchases_pagination, _, _ = get_paginated_results(
        base_purchases_query,
        endpoint_name='main_bp.achat_stock',
        per_page_config_key='SALES_PER_PAGE',
        date=selected_date_str
    )

    return render_template(
        "main/achat_stock.html",
        form=form,
        segment="stock",
        sub_segment="achat_stock",
        stock_purchases=stock_purchases_pagination.items,
        stock_purchases_pagination=stock_purchases_pagination,
        selected_date=selected_date_str
    )


# Edit Stock Purchase
@bp.route("/achat_stock/editer/<int:purchase_id>", methods=["GET", "POST"])
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
                network_enum = NetworkType(
                    network_type_string_from_form.lower())
            except ValueError:
                flash(        f"Le type de réseau '{network_type_string_from_form}' n'est pas valide.",
                    "danger",
                )
                return render_template(
                    "main/edit_stock_purchase.html",
                    form=form,
                    purchase=purchase,
                    page_title="Editer Achat de Stock",
                    segment="stock",
                    sub_segment="achat_stock",
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
                flash(        "Veuillez sélectionner ou entrer un prix d'achat et un prix de vente valides.",
                    "danger",
                )
                return render_template(
                    "main/edit_stock_purchase.html",
                    form=form,
                    purchase=purchase,
                    page_title="Editer Achat de Stock",
                    segment="stock",
                    sub_segment="achat_stock",
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
            new_stock_item = Stock.query.filter_by(
                network=network_enum).first()
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
            return redirect(url_for("main_bp.achat_stock"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error updating stock purchase {purchase_id}: {e}"
            )
            flash(    f"Une erreur est survenue lors de la mise à jour: {e}", "danger")

    return render_template(
        "main/edit_stock_purchase.html",
        form=form,
        purchase=purchase,
        page_title="Editer Achat de Stock",
        segment="stock",
        sub_segment="achat_stock",
    )


# Delete Stock Purchase
@bp.route("/achat_stock/supprimer/<int:purchase_id>", methods=["GET", "POST"])
@login_required
@superadmin_required
def delete_stock_purchase(purchase_id):
    purchase = StockPurchase.query.get_or_404(purchase_id)

    if request.method == "POST":
        try:
            # Revert the stock balance
            stock_item = Stock.query.filter_by(
                network=purchase.network).first()
            if stock_item:
                stock_item.balance -= purchase.amount_purchased
                # Note: deleting a purchase does not adjust buying_price_per_unit/selling_price_per_unit
                # on Stock because those reflect the *latest* purchase. If the deleted purchase was
                # the latest, these prices on Stock might become "stale" until a new purchase occurs.
                # A more complex system might look for the next latest purchase to update them,
                # but for simplicity, we leave them as is.
                db.session.add(stock_item)
            else:
                flash(        "Erreur: L'article de stock correspondant est introuvable.",
                    "danger",
                )
                return redirect(url_for("main_bp.achat_stock"))

            db.session.delete(purchase)
            db.session.commit()
            flash(    f"Achat de stock #{purchase_id} supprimé avec succès!", "success")
            return redirect(url_for("main_bp.achat_stock"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error deleting stock purchase {purchase_id}: {e}"
            )
            flash(    f"Une erreur est survenue lors de la suppression: {e}", "danger")
            return redirect(url_for("main_bp.achat_stock"))

    flash("Confirmez la suppression de l'achat de stock.", "warning")
    return render_template(
        "main/confirm_delete_stock_purchase.html",
        purchase=purchase,
        page_title="Confirmer Suppression",
        segment="stock",
        sub_segment="achat_stock",
    )


@bp.route("/vente_stock", methods=["GET", "POST"])
@login_required
@vendeur_required
def vente_stock():
    form = SaleForm()

    # --- 1. SETUP FORM DATA ---
    # Populate client choices dynamically
    clients = Client.query.filter_by(
        is_active=True).order_by(Client.name).all()
    client_choices = [("", "Sélectionnez un client existant")]
    client_choices.extend([(str(c.id), c.name) for c in clients])
    form.existing_client_id.choices = client_choices

    # Pre-fill empty rows for the FieldList on GET
    if request.method == "GET" and not form.sale_items:
        for _ in range(3):
            form.sale_items.append_entry()

    # --- 2. HANDLE POST (Processing the Sale) ---
    if form.validate_on_submit():
        try:
            # A. Resolve Client
            client = None
            client_name_adhoc = None

            if form.client_choice.data == "existing":
                client_id = form.existing_client_id.data
                if not client_id:
                    raise ValueError(
                        "Veuillez sélectionner un client existant.")
                client = Client.query.get(int(client_id))
                if not client:
                    raise ValueError("Client sélectionné invalide.")

            elif form.client_choice.data == "new":
                client_name_adhoc = form.new_client_name.data
                if not client_name_adhoc:
                    raise ValueError(
                        "Veuillez entrer le nom du nouveau client.")

            # B. Process Sale Items
            total_amount_due = Decimal("0.00")
            sale_items_to_add = []

            # Check if list is empty
            # (Note: Logic depends on how your form handles empty removals,
            # usually we filter out empty entries here)

            for index, item_data in enumerate(form.sale_items.entries):
                # Skip empty entries if your logic allows it, otherwise validate
                network_enum = item_data.form.network.data
                quantity = item_data.form.quantity.data

                # Basic validation skipping empty rows if needed
                if not network_enum or not quantity:
                    continue

                network_type = NetworkType[network_enum]
                price_override = item_data.form.price_per_unit_applied.data

                # Check Stock Availability
                stock_item = Stock.query.filter_by(
                    network=network_type).first()

                if not stock_item:
                    raise ValueError(
                        f"Réseau '{network_type.value}' introuvable en stock.")

                if quantity > stock_item.balance:
                    raise ValueError(
                        f"Stock insuffisant pour {network_type.value}. "
                        f"Dispo: {stock_item.balance}, Demandé: {quantity}."
                    )

                # Determine Price
                final_unit_price = None
                if price_override is not None:
                    final_unit_price = price_override
                elif stock_item.selling_price_per_unit and stock_item.selling_price_per_unit > 0:
                    final_unit_price = stock_item.selling_price_per_unit
                else:
                    raise ValueError(
                        f"Prix introuvable pour '{network_type.value}'. "
                        "Définissez un prix dans le stock ou manuellement."
                    )

                # Calculate Line Totals
                subtotal_raw = quantity * final_unit_price
                subtotal = custom_round_up(subtotal_raw)

                # Prepare Object
                new_item = SaleItem(
                    network=network_type,
                    quantity=quantity,
                    price_per_unit_applied=final_unit_price,
                    subtotal=subtotal
                )

                # Deduct Stock Immediately (Optimistic Locking assumed or non-issue for scale)
                stock_item.balance -= quantity
                db.session.add(stock_item)

                sale_items_to_add.append(new_item)
                total_amount_due += subtotal

            if not sale_items_to_add:
                raise ValueError(
                    "Veuillez ajouter au moins un article valide.")

            # C. Finalize Financials
            cash_paid = form.cash_paid.data if form.cash_paid.data is not None else Decimal(
                "0.00")
            debt_amount = total_amount_due - cash_paid

            if debt_amount < 0:
                raise ValueError(
                    "Le montant payé ne peut pas dépasser le total dû.")

            # D. Save Sale
            new_sale = Sale(
                vendeur=current_user,
                client=client,
                client_name_adhoc=client_name_adhoc,
                total_amount_due=total_amount_due,
                cash_paid=cash_paid,
                debt_amount=debt_amount
            )
            new_sale.sale_items.extend(sale_items_to_add)

            db.session.add(new_sale)
            db.session.commit()

            flash("Vente enregistrée avec succès!", "success")
            return redirect(url_for("main_bp.vente_stock"))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), "danger")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Sale Error: {e}")
            flash("Une erreur système est survenue.", "danger")

    # Handle Form Validation Errors (if submit failed but no exception raised)
    elif form.errors:
        flash("Veuillez corriger les erreurs dans le formulaire.", "danger")
        # Optional: Detailed error logging to flash can be done here if desired

    # --- 3. HANDLE GET (Data Fetching & Pagination) ---

    # A. Get Date Context using your Utility
    # This automatically checks request.args for 'date' and defaults to Today
    base_sales_query, ctx = get_sales_history_query(date_filter=True)
    selected_date_str = ctx.get('date_str')

    # B. Paginate using your Utility
    sales_pagination, _, _ = get_paginated_results(
        base_sales_query,
        endpoint_name='main_bp.vente_stock',
        per_page_config_key='SALES_PER_PAGE',
        date=selected_date_str
    )

    return render_template(
        "main/vente_stock.html",
        form=form,
        segment="stock",
        sub_segment="vente_stock",
        # Pass the pagination object for the macro
        sales_pagination=sales_pagination,
        # Pass the date string for the Date Filter macro
        selected_date=selected_date_str
    )


@bp.route("/update-sale-cash/<int:sale_id>", methods=["POST"])
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
        return redirect(url_for("main_bp.vente_stock"))

    if new_cash < 0:
        flash("Le paiement ne peut pas être négatif.", "danger")
        return redirect(url_for("main_bp.vente_stock"))

    # Calculate new debt
    new_debt = sale.total_amount_due - new_cash

    if new_debt < 0:
        flash("Le paiement ne peut pas dépasser le montant total dû.", "danger")
        return redirect(url_for(""))

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

    return redirect(url_for("main_bp.vente_stock"))


@bp.route("/edit_sale/<int:sale_id>", methods=["GET", "POST"])
@login_required
@vendeur_required
def edit_sale(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    form = SaleForm()

    # Populate client choices
    clients = Client.query.filter_by(
        is_active=True).order_by(Client.name).all()
    client_choices = [("", "Sélectionnez un client existant")]
    client_choices.extend([(str(client.id), client.name)
                          for client in clients])
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
        while len(form.sale_items) > 0:
            form.sale_items.pop_entry()

        for item in sale.sale_items:
            item_form = form.sale_items.append_entry()
            item_form.network.data = item.network.name
            item_form.quantity.data = item.quantity
            item_form.price_per_unit_applied.data = item.price_per_unit_applied

        form.cash_paid.data = sale.cash_paid

    if form.validate_on_submit():
        db.session.begin_nested()  # Start a nested transaction / savepoint

        try:
            # Store old quantities per network for precise reversion
            old_quantities_map = {
                item.network: item.quantity for item in sale.sale_items
            }

            # 1. Delete old SaleItems associated with this sale
            for item_to_delete in list(sale.sale_items):
                db.session.delete(item_to_delete)
            # SQLAlchemy will handle clearing the relationship on `sale` after commit/flush

            # 2. Revert stock based on old quantities *after* deleting SaleItems
            for network, quantity in old_quantities_map.items():
                stock_item = Stock.query.filter_by(network=network).first()
                if stock_item:
                    stock_item.balance += quantity
                    db.session.add(stock_item)
                    print(
                        f"Reverted stock for {network.value}: New balance is {stock_item.balance}"
                    )

            # 3. Update Sale header data
            client = None
            client_name_adhoc = None
            if form.client_choice.data == "existing":
                client_id = form.existing_client_id.data
                if client_id:
                    client = Client.query.get(int(client_id))
                    if not client:
                        raise ValueError(
                            "Client existant sélectionné invalide.")
                else:
                    raise ValueError(
                        "Veuillez sélectionner un client existant.")
            elif form.client_choice.data == "new":
                client_name_adhoc = form.new_client_name.data
                if not client_name_adhoc:
                    raise ValueError(
                        "Veuillez entrer le nom du nouveau client.")

            sale.client = client
            sale.client_name_adhoc = client_name_adhoc if not client else None
            sale.updated_at = datetime.utcnow()

            total_amount_due = Decimal("0.00")
            sale_items_to_add = []
            errors_during_sale = []

            # 4. Process new sale items and link to the existing sale
            for item_data in form.sale_items.entries:
                if not item_data.form.validate():
                    for field_name, field_errors in item_data.form.errors.items():
                        for error in field_errors:
                            errors_during_sale.append(
                                f"Erreur dans l'article: {item_data.form[field_name].label.text}: {error}"
                            )
                    continue

                # Ensure NetworkType is correctly parsed from the form data string
                try:
                    network_type = NetworkType[item_data.form.network.data]
                except KeyError:
                    errors_during_sale.append(
                        f"Type de réseau invalide: {item_data.form.network.data}"
                    )
                    continue

                quantity = item_data.form.quantity.data
                price_per_unit_applied = item_data.form.price_per_unit_applied.data

                stock_item = Stock.query.filter_by(
                    network=network_type).first()

                if not stock_item:
                    errors_during_sale.append(
                        f"Réseau '{network_type.value}' non trouvé en stock."
                    )
                    continue

                # IMPORTANT:
                if quantity > stock_item.balance:
                    errors_during_sale.append(
                        f"Quantité insuffisante pour {network_type.value}. Disponible: {stock_item.balance}, Demandé: {quantity}."
                    )
                    continue

                # Determine the price_per_unit_applied (from previous logic)
                if price_per_unit_applied is None:
                    if (
                        stock_item.selling_price_per_unit is not None
                    ):  # Prefer current selling price from stock
                        price_per_unit_applied = stock_item.selling_price_per_unit
                    else:
                        latest_purchase = (
                            StockPurchase.query.filter_by(
                                stock_item=stock_item)
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

                # Ensure price_per_unit_applied is Decimal
                if not isinstance(price_per_unit_applied, Decimal):
                    price_per_unit_applied = Decimal(
                        str(price_per_unit_applied))

                # Calculate rounded subtotal using your custom_round_up function
                if price_per_unit_applied is None:
                    flash(            f"Prix unitaire non défini pour '{network_type.value}'.",
                        "danger",
                    )
                    continue
                item_subtotal_unrounded = quantity * price_per_unit_applied
                subtotal = custom_round_up(amount=item_subtotal_unrounded)

                new_sale_item = SaleItem(
                    network=network_type,
                    quantity=quantity,
                    price_per_unit_applied=price_per_unit_applied,
                    subtotal=subtotal,
                    sale=sale,
                )
                sale_items_to_add.append(new_sale_item)
                total_amount_due += subtotal

                # Update stock balance for new items
                stock_item.balance -= quantity
                db.session.add(stock_item)

            if errors_during_sale:
                db.session.rollback()
                for error in errors_during_sale:
                    flash(error, "danger")
                # Render the edit template, not the create template
                return render_template(
                    "main/edit_sale.html",
                    form=form,
                    sale=sale,
                    segment="stock",
                    sub_segment="vente_stock",
                )

            if not sale_items_to_add:
                db.session.rollback()
                flash("Veuillez ajouter au moins un article à la vente.", "danger")
                return render_template(
                    "main/edit_sale.html",
                    form=form,
                    sale=sale,
                    segment="stock",
                    sub_segment="vente_stock",
                )

            # Add new sale items to the sale (SQLAlchemy will link them)
            for item in sale_items_to_add:
                db.session.add(item)

            # 5. Update total_amount_due, cash_paid, debt_amount on the Sale
            sale.total_amount_due = total_amount_due
            cash_paid = form.cash_paid.data
            if cash_paid is None:
                cash_paid = Decimal("0.00")
            sale.cash_paid = cash_paid
            sale.debt_amount = total_amount_due - cash_paid
            if sale.debt_amount < Decimal("0.00"):
                raise ValueError(
                    "L'argent donné ne peut pas dépasser le montant total dû."
                )

            db.session.commit()
            flash("Vente modifiée avec succès!", "success")
            return redirect(url_for("main_bp.vente_stock"))

        except ValueError as e:
            db.session.rollback()
            flash(f"Erreur lors de la modification de la vente: {e}", "danger")
            return render_template(
                "main/edit_sale.html",
                form=form,
                sale=sale,
                segment="stock",
                sub_segment="vente_stock",
            )
        except Exception as e:
            db.session.rollback()
            flash(    f"Erreur inattendue lors de la modification de la vente: {e}", "danger"
            )
            print(f"Error during sale edit: {e}")
            return render_template(
                "main/edit_sale.html",
                form=form,
                sale=sale,
                segment="stock",
                sub_segment="vente_stock",
            )

    return render_template(
        "main/edit_sale.html",
        form=form,
        sale=sale,
        segment="stock",
        sub_segment="vente_stock",
    )


@bp.route("/delete_sale/<int:sale_id>", methods=["GET", "POST"])
@login_required
@vendeur_required
def delete_sale(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    confirm_form = DeleteConfirmForm()

    if request.method == "POST":
        print("POST request received! Trying to delete...")

        try:
            db.session.begin_nested()

            for sale_item in sale.sale_items:
                stock_item = Stock.query.filter_by(
                    network=sale_item.network).first()
                if stock_item:
                    stock_item.balance += sale_item.quantity
                    db.session.add(stock_item)
                    print(
                        f"Reverted stock for {sale_item.network.value}: New balance is {stock_item.balance}"
                    )
                else:
                    current_app.logger.warning(
                        f"Warning: Stock item for network {sale_item.network.value} not found while deleting sale {sale_id}. Stock not fully reverted."
                    )

            for item_to_delete in list(sale.sale_items):
                db.session.delete(item_to_delete)

            db.session.delete(sale)
            db.session.commit()
            print("Sale deleted successfully!")
            flash(f"Vente #{sale_id} supprimée avec succès!", "success")
            return redirect(url_for("main_bp.vente_stock"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error deleting sale {sale_id}: {e}", exc_info=True
            )
            flash(    f"Une erreur est survenue lors de la suppression de la vente: {e}",
                "danger",
            )
            return redirect(url_for("main_bp.vente_stock"))

    flash("Confirmez la suppression de la vente.", "warning")
    return render_template(
        "main/confirm_delete_sale.html",
        sale=sale,
        confirm_form=confirm_form,
        page_title="Confirmer Suppression Vente",
        segment="stock",
        sub_segment="vente_stock",
    )


@bp.route("/view_sale_details/<int:sale_id>", methods=["GET"])
@login_required
def view_sale_details(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    return render_template(
        "main/sale_details.html",
        sale=sale,
        segment="stock",
        sub_segment="vente_stock",
    )


# sorties_cash route
@bp.route("/sorties_cash", methods=["GET"])
@login_required
def sorties_cash():
    # Fetch all cash movements for display
    all_outflows = CashOutflow.query.order_by(
        CashOutflow.created_at.desc()).all()
    all_inflows = CashInflow.query.order_by(CashInflow.created_at.desc()).all()

    # Calculate total cash outflow
    total_outflow = (
        sum(outflow.amount for outflow in all_outflows)
        if all_outflows
        else Decimal("0.00")
    )

    # Note: The previous logic for total_inflow was overwritten here.
    # total_inflow should combine actual CashInflow records AND cash_paid from sales.
    total_cash_inflows_records = (
        sum(inflow.amount for inflow in all_inflows) if all_inflows else Decimal("0.00")
    )

    # Get total cash paid directly from Sales (initial payment at sale time)
    # Use scalar() to get the sum directly, it will be None if no sales, so handle it.
    all_sales_cash_paid_sum = db.session.query(
        db.func.sum(Sale.cash_paid)).scalar()
    total_sales_cash_paid = (
        all_sales_cash_paid_sum if all_sales_cash_paid_sum else Decimal("0.00")
    )

    total_inflow = total_cash_inflows_records + total_sales_cash_paid

    return render_template(
        "main/sorties_cash.html",
        outflows=all_outflows,
        inflows=all_inflows,
        total_outflow=total_outflow,
        total_inflow=total_inflow,
        segment="stock",
        sub_segment="Sorties_Cash",
    )


# Enregistre une Sortie (Cash Outflow)
@bp.route("/enregistrer_sortie", methods=["GET", "POST"])
@login_required
@vendeur_required
def enregistrer_sortie():
    form = CashOutflowForm(request.form)
    page_title = "Gestion Cash"
    sub_page_title = "Enregistrer une Nouvelle Sortie"

    if "submit" in request.form:
        if form.validate_on_submit():
            try:
                new_outflow = CashOutflow(
                    amount=form.amount.data,
                    category=form.category.data,
                    description=form.description.data,
                    # FIX IS HERE: Assign the User object, not its ID
                    # Assign the current_user object (which is a User model instance)
                    recorded_by=current_user,
                )
                db.session.add(new_outflow)
                db.session.commit()

                flash("Sortie de caisse enregistrée avec succès!", "success")
                return redirect(url_for("main_bp.sorties_cash"))

            except Exception as e:
                db.session.rollback()
                flash(        f"Erreur lors de l'enregistrement de la sortie: {str(e)}", "danger"
                )
                print(f"Error saving cash outflow: {e}")

        else:
            for field, errors in form.errors.items():
                for error in errors:
                    flash(            f"Erreur dans le champ '{form[field].label.text}': {error}",
                        "danger",
                    )

    return render_template(
        "main/enregistrer_sortie.html",
        form=form,
        page_title=page_title,
        sub_page_title=sub_page_title,
        segment="enregistrer_sortie",
    )


# Encaisser une Dette (Debt Collection)
@bp.route("/sorties_cash/encaisser_dette", methods=["GET", "POST"])
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
                flash(        f"Le montant payé ({amount_paid:,.2f} FC) est supérieur à la dette restante ({sale_to_update.debt_amount:,.2f} FC). Ajustement à la dette.",
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
            flash(    f"Paiement de {amount_paid:,.2f} FC pour la vente #{sale_id} enregistré avec succès. Nouvelle dette: {sale_to_update.debt_amount:,.2f} FC.",
                "success",
            )
            return redirect(
                url_for("main_bp.sorties_cash")
            )  # Redirect back to overview
        except InvalidOperation:
            flash("Montant invalide. Veuillez entrer un nombre valide.", "danger")
            db.session.rollback()
        except ValueError as e:
            flash(f"Erreur de validation: {e}", "danger")
            db.session.rollback()
        except Exception as e:
            db.session.rollback()
            flash(    f"Erreur lors de l'enregistrement du paiement: {e}", "danger")
            print(f"Error recording debt collection: {e}")

    return render_template(
        "main/encaisser_dette.html",
        form=form,
        segment="stock",
        sub_segment="Sorties_Cash",
        sub_page_title="Encaisser Dette",
    )


@bp.route("/rapports", methods=["GET"])
@login_required
@superadmin_required
def rapports():
    page_title = "Rapport Journalier"

    # --- REFACTORED: Step 1 & 2 replaced with single Utility Call ---
    # This retrieves selected_date, is_today flag, and correct UTC ranges
    ctx = get_date_context()

    current_app.logger.debug(
        f"Single Report requested for: {ctx['selected_date']}")

    # Get recent purchases (filtered by date, desc order)
    purchase_query, _ = get_stock_purchase_history_query(date_filter=True)
    recent_purchases = purchase_query.limit(5).all()

    # Get recent sales (filtered by date, desc order)
    sales_query, _ = get_sales_history_query(date_filter=True)
    recent_sales = sales_query.limit(5).all()

    # 3. Initialize Data Structures (Empty State)
    networks = list(NetworkType.__members__.values())

    def zero_money(): return Decimal("0.00")

    report_data = {
        network.name: {
            "initial_stock": zero_money(),
            "purchased_stock": zero_money(),
            "sold_stock": zero_money(),
            "final_stock": zero_money(),
            "virtual_value": zero_money(),
            "debt_amount": zero_money(),
            "sales_from_transactions_value": zero_money(),
            "network": network,
        } for network in networks
    }

    grand_totals = {
        "initial_stock": zero_money(),
        "purchased_stock": zero_money(),
        "sold_stock": zero_money(),
        "final_stock": zero_money(),
        "virtual_value": zero_money(),
        "total_debts": zero_money(),
        "total_calculated_sold_stock": zero_money()
    }

    # 4. Fetch Data Logic

    # SCENARIO A: LIVE REPORT (Today)
    # We use the boolean flag from our utility
    if ctx['is_today']:
        current_app.logger.info("Fetching LIVE report data for today.")

        # We use the pre-calculated UTC ranges from the utility context
        calculated_data, total_sales_val, total_live_debts = get_daily_report_data(
            current_app,
            ctx['selected_date'],
            start_of_utc_range=ctx['start_utc'],
            end_of_utc_range=ctx['end_utc'],
        )

        # Map live calculations to view structure
        for network_name, data in calculated_data.items():
            report_data[network_name].update({
                "initial_stock": data["initial_stock"],
                "purchased_stock": data["purchased_stock"],
                "sold_stock": data["sold_stock_quantity"],
                "final_stock": data["final_stock"],
                "virtual_value": data["virtual_value"],
                "sales_from_transactions_value": data["sold_stock_value"],
            })

            # Accumulate Grand Totals
            grand_totals["initial_stock"] += data["initial_stock"]
            grand_totals["purchased_stock"] += data["purchased_stock"]
            grand_totals["sold_stock"] += data["sold_stock_quantity"]
            grand_totals["final_stock"] += data["final_stock"]
            grand_totals["virtual_value"] += data["virtual_value"]

        grand_totals["total_debts"] = total_live_debts or zero_money()

    # SCENARIO B: HISTORICAL REPORT (Past Date)
    else:
        current_app.logger.info(
            f"Fetching HISTORICAL report for {ctx['selected_date']}.")

        # Fetch the single overall summary for that day
        overall_report = DailyOverallReport.query.filter_by(
            report_date=ctx['selected_date']).first()

        if overall_report:
            # Populate Grand Totals directly from the saved report
            grand_totals["initial_stock"] = overall_report.total_initial_stock
            grand_totals["purchased_stock"] = overall_report.total_purchased_stock
            grand_totals["sold_stock"] = overall_report.total_sold_stock
            grand_totals["final_stock"] = overall_report.total_final_stock
            grand_totals["virtual_value"] = overall_report.total_virtual_value
            grand_totals["total_debts"] = overall_report.total_debts

            # Fetch detailed breakdown per network
            daily_network_reports = DailyStockReport.query.filter_by(
                report_date=ctx['selected_date']).all()

            for r in daily_network_reports:
                if r.network.name in report_data:
                    report_data[r.network.name].update({
                        "initial_stock": r.initial_stock_balance,
                        "purchased_stock": r.purchased_stock_amount,
                        "sold_stock": r.sold_stock_amount,
                        "final_stock": r.final_stock_balance,
                        "virtual_value": r.virtual_value,
                    })
        else:
            flash(    f"Aucun rapport archivé trouvé pour le {ctx['date_str']}.", "warning")

    # 5. Final Calculation (Applied to both scenarios)
    grand_totals["total_calculated_sold_stock"] = (
        grand_totals["initial_stock"]
        + grand_totals["purchased_stock"]
        - grand_totals["final_stock"]
    )

    return render_template(
        "main/rapports.html",
        page_title=page_title,
        networks=networks,
        report_data=report_data,
        grand_totals=grand_totals,
        selected_date=ctx['date_str'],
        # Pass the lists to the template
        recent_purchases=recent_purchases,
        recent_sales=recent_sales
    )


@bp.route("/rapports/archive", methods=["POST"])
@login_required
@superadmin_required
def archive_daily_report():
    # 1. Get the date from the hidden input in your HTML form
    date_str = request.form.get('date_to_archive')

    if not date_str:
        flash("Aucune date spécifiée pour l'archivage.", "danger")
        return redirect(url_for('main_bp.rapports'))

    try:
        # Convert string 'YYYY-MM-DD' to a date object
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # 2. Call your existing helper function!
        # This will create or update the DailyStockReport and DailyOverallReport
        update_daily_reports(
            current_app._get_current_object(),
            report_date_to_update=report_date
        )

        flash(f"Le rapport du {date_str} a été validé et archivé avec succès.", "success")

    except Exception as e:
        current_app.logger.error(f"Erreur d'archivage manuelle: {str(e)}")
        flash(f"Une erreur est survenue lors de l'archivage : {str(e)}", "danger")

    # Redirect back to the reports page for that specific date
    return redirect(url_for('main_bp.rapports', date=date_str))



@bp.route("/profile")
@login_required
def profile():

    profile_form = UpdateProfileForm(
        original_username=current_user.username,
        original_email=current_user.email,
    )

    password_form = ChangePasswordForm()

    # Pré-remplissage
    profile_form.username.data = current_user.username
    profile_form.email.data = current_user.email
    profile_form.phone.data = current_user.phone

    return render_template(
        "main/profile.html",
        profile_form=profile_form,
        password_form=password_form,
        num_clients_created=len(current_user.clients or []),
        num_sales_made=len(current_user.sales or []),
        num_stock_purchases=current_user.stock_purchases_made.count()
        if hasattr(current_user, "stock_purchases_made")
        else 0,
    )



@bp.route("/profile/update-info", methods=["POST"])
@login_required
def update_profile_info():

    form = UpdateProfileForm(
        original_username=current_user.username,
        original_email=current_user.email,
    )

    if form.validate_on_submit():

        current_user.username = form.username.data
        current_user.email = form.email.data
        current_user.phone = form.phone.data

        db.session.commit()
        flash("Profil mis à jour avec succès.", "success")

    else:
        flash("Erreur lors de la mise à jour du profil.", "danger")

    return redirect(url_for("main_bp.profile"))



@bp.route("/profile/change-password", methods=["POST"])
@login_required
def change_password():

    form = ChangePasswordForm()

    if form.validate_on_submit():

        if not current_user.check_password(form.current_password.data):
            flash("Mot de passe actuel incorrect.", "danger")
            return redirect(url_for("main_bp.profile"))

        current_user.set_password(form.new_password.data)
        db.session.commit()

        flash("Mot de passe modifié avec succès.", "success")

    else:
        flash("Erreur lors du changement du mot de passe.", "danger")

    return redirect(url_for("main_bp.profile"))




# Client Map route
@bp.route("/client-map", methods=["GET"])
@login_required
@vendeur_required
def client_map():
    """
    Renders a map displaying clients based on their GPS coordinates.
    Clients are color-coded based on their total purchases (high-value = green, medium = orange, low = blue).
    """

    # Enhanced client data with purchase history
    # In production, this would come from your database
    hardcoded_client_locations = [
        {
            "id": 1,
            "name": "Boutique Mama Zawadi",
            "address": "Avenue Patrice Lumumba 45, Panzi",
            "lat": -2.5380,
            "lng": 28.8580,
            "phone_airtel": "0991234567",
            "phone_orange": "0841234567",
            "purchases_last_week": {
                "airtel": 150000,
                "orange": 120000,
                "vodacom": 80000,
                "africel": 50000
            },
            "total_purchases": 400000,  # High value client
            "last_purchase_date": "2024-01-25"
        },
        {
            "id": 2,
            "name": "Kiosk Bénédiction",
            "address": "Rue de l'Église 12, Panzi",
            "lat": -2.5420,
            "lng": 28.8620,
            "phone_airtel": "0997654321",
            "phone_orange": "0847654321",
            "purchases_last_week": {
                "airtel": 200000,
                "orange": 180000,
                "vodacom": 150000,
                "africel": 70000
            },
            "total_purchases": 600000,  # High value client
            "last_purchase_date": "2024-01-26"
        },
        {
            "id": 3,
            "name": "Phone House Ibanda",
            "address": "Avenue du Commerce 78, Ibanda",
            "lat": -2.5350,
            "lng": 28.8550,
            "phone_airtel": "0991122334",
            "phone_orange": "0841122334",
            "purchases_last_week": {
                "airtel": 50000,
                "orange": 40000,
                "vodacom": 30000,
                "africel": 20000
            },
            "total_purchases": 140000,  # Medium value client
            "last_purchase_date": "2024-01-24"
        },
        {
            "id": 4,
            "name": "Ets. Mumbere Telecom",
            "address": "Boulevard du Lac 156, Panzi",
            "lat": -2.5450,
            "lng": 28.8600,
            "phone_airtel": "0994455667",
            "phone_orange": "0844455667",
            "purchases_last_week": {
                "airtel": 300000,
                "orange": 250000,
                "vodacom": 200000,
                "africel": 100000
            },
            "total_purchases": 850000,  # Very high value client
            "last_purchase_date": "2024-01-26"
        },
        {
            "id": 5,
            "name": "Cyber Café Espoir",
            "address": "Rue des Écoles 34, Ibanda",
            "lat": -2.5320,
            "lng": 28.8530,
            "phone_airtel": "0998877665",
            "phone_orange": "0848877665",
            "purchases_last_week": {
                "airtel": 25000,
                "orange": 20000,
                "vodacom": 15000,
                "africel": 10000
            },
            "total_purchases": 70000,  # Low value client
            "last_purchase_date": "2024-01-23"
        },
        {
            "id": 6,
            "name": "Alimentation La Grâce",
            "address": "Avenue Industrielle 89, Panzi",
            "lat": -2.5400,
            "lng": 28.8650,
            "phone_airtel": "0993344556",
            "phone_orange": "0843344556",
            "purchases_last_week": {
                "airtel": 80000,
                "orange": 60000,
                "vodacom": 50000,
                "africel": 30000
            },
            "total_purchases": 220000,  # Medium value client
            "last_purchase_date": "2024-01-25"
        },
        {
            "id": 7,
            "name": "Pharmacie du Peuple",
            "address": "Rue de la Santé 23, Ibanda",
            "lat": -2.5370,
            "lng": 28.8510,
            "phone_airtel": "0996677889",
            "phone_orange": "0846677889",
            "purchases_last_week": {
                "airtel": 15000,
                "orange": 10000,
                "vodacom": 8000,
                "africel": 5000
            },
            "total_purchases": 38000,  # Low value client
            "last_purchase_date": "2024-01-22"
        },
        {
            "id": 8,
            "name": "Grand Marché Mobile",
            "address": "Place du Marché Central, Panzi",
            "lat": -2.5410,
            "lng": 28.8570,
            "phone_airtel": "0992233445",
            "phone_orange": "0842233445",
            "purchases_last_week": {
                "airtel": 180000,
                "orange": 150000,
                "vodacom": 120000,
                "africel": 80000
            },
            "total_purchases": 530000,  # High value client
            "last_purchase_date": "2024-01-26"
        },
    ]

    # Calculate value tier for each client (for marker coloring)
    # Thresholds: High >= 400,000 FC, Medium >= 100,000 FC, Low < 100,000 FC
    HIGH_VALUE_THRESHOLD = 400000
    MEDIUM_VALUE_THRESHOLD = 100000

    for client in hardcoded_client_locations:
        total = client["total_purchases"]
        if total >= HIGH_VALUE_THRESHOLD:
            client["value_tier"] = "high"
        elif total >= MEDIUM_VALUE_THRESHOLD:
            client["value_tier"] = "medium"
        else:
            client["value_tier"] = "low"

    client_locations = hardcoded_client_locations

    # Calculate summary statistics for the page
    total_clients = len(client_locations)
    total_weekly_sales = sum(c["total_purchases"] for c in client_locations)
    high_value_count = sum(
        1 for c in client_locations if c["value_tier"] == "high")

    # Network breakdown
    network_totals = {
        "airtel": sum(c["purchases_last_week"]["airtel"] for c in client_locations),
        "orange": sum(c["purchases_last_week"]["orange"] for c in client_locations),
        "vodacom": sum(c["purchases_last_week"]["vodacom"] for c in client_locations),
        "africel": sum(c["purchases_last_week"]["africel"] for c in client_locations),
    }

    # Set default center for Panzi/Ibanda area
    default_center_lat = -2.5395
    default_center_lng = 28.8575

    # If clients exist, center on their average location
    if client_locations:
        avg_lat = sum(loc["lat"]
                      for loc in client_locations) / len(client_locations)
        avg_lng = sum(loc["lng"]
                      for loc in client_locations) / len(client_locations)
        default_center_lat = avg_lat
        default_center_lng = avg_lng

    return render_template(
        "main/client_map.html",
        client_locations=client_locations,
        default_center_lat=default_center_lat,
        default_center_lng=default_center_lng,
        total_clients=total_clients,
        total_weekly_sales=total_weekly_sales,
        high_value_count=high_value_count,
        network_totals=network_totals,
        segment="client_map",
    )
